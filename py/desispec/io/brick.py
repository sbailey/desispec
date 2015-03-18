"""
I/O routines for working with brick files.

See doc/DESI_SPECTRO_REDUX/PRODNAME/bricks/BRICKID/brick-BRICKID.rst in desiDataModel
for a description of the brick file data model.
"""

import os
import os.path

import numpy as np
import astropy.io.fits

import desispec.io.util

class Brick(object):
    """
    Represents objects in a single brick and possibly also a single band b,r,z.

    The constructor will open an existing file and create a new file and parent
    directory if necessary.  The :meth:`close` method must be called for any updates
    or new data to be recorded. Successful completion of the constructor does not
    guarantee that :meth:`close` will suceed.

    Args:
        path(str): Path to the brick file to open.
        mode(str): File access mode to use. Should normally be 'readonly' or 'update'.
            Use 'update' to create a new file and its parent directory if necessary.
        header: An optional header specification used to create a new file. See
            :func:`desispec.io.util.fitsheader` for details on allowed values.

    Raises:
        RuntimeError: Invalid mode requested.
        IOError: Unable to open existing file in 'readonly' mode.
        OSError: Unable to create a new parent directory in 'update' mode.
    """
    def __init__(self,path,mode = 'readonly',header = None):
        if mode not in ('readonly','update'):
            raise RuntimeError('Invalid mode %r' % mode)
        self.path = path
        self.mode = mode
        # Create a new file if necessary.
        if self.mode == 'update' and not os.path.exists(self.path):
            # Create the parent directory, if necessary.
            head,tail = os.path.split(self.path)
            if not os.path.exists(head):
                os.makedirs(head)
            # Create empty HDUs. It would be good to refactor io.frame to avoid any duplication here.
            hdr = desispec.io.util.fitsheader(header)
            hdr['EXTNAME'] = ('FLUX', 'no dimension')
            hdu0 = astropy.io.fits.PrimaryHDU(header = hdr)
            hdr['EXTNAME'] = ('IVAR', 'no dimension')
            hdu1 = astropy.io.fits.ImageHDU(header = hdr)
            hdr['EXTNAME'] = ('WAVELENGTH', '[Angstroms]')
            hdu2 = astropy.io.fits.ImageHDU(header = hdr)
            hdr['EXTNAME'] = ('RESOLUTION', 'no dimension')
            hdu3 = astropy.io.fits.ImageHDU(header = hdr)
            hdr['EXTNAME'] = ('FIBERMAP', 'no dimension')
            # Use the columns from fibermap with a few extras added.
            columns = desispec.io.fibermap.fibermap_columns[:]
            columns.extend([
                ('NIGHT','i4'),
                ('EXPID','i4'),
                ])
            data = np.empty(shape = (0,),dtype = columns)
            hdu4 = astropy.io.fits.BinTableHDU(data = data,header = hdr)
            # Add comments for fibermap columns.
            num_fibermap_columns = len(desispec.io.fibermap.fibermap_comments)
            for i in range(1,1+num_fibermap_columns):
                key = 'TTYPE%d' % i
                name = hdu4.header[key]
                comment = desispec.io.fibermap.fibermap_comments[name]
                hdu4.header[key] = (name,comment)
            # Add comments for our additional columns.
            hdu4.header['TTYPE%d' % (1+num_fibermap_columns)] = ('NIGHT','Night of exposure YYYYMMDD')
            hdu4.header['TTYPE%d' % (2+num_fibermap_columns)] = ('EXPID','Exposure ID')
            self.hdu_list = astropy.io.fits.HDUList([hdu0,hdu1,hdu2,hdu3,hdu4])
        else:
            self.hdu_list = astropy.io.fits.open(path,mode = self.mode)
            if len(self.hdu_list) != 5:
                raise RuntimeError('Unexpected number of HDUs (%d) in %s' % (
                    len(self.hdu_list),self.path))

    def add_objects(self,flux,ivar,wave,resolution,object_data,night,expid):
        """
        Add a list of objects to this brick file from the same night and exposure.

        Args:
            flux(numpy.ndarray): Array of (nobj,nwave) flux values for nobj objects tabulated
                at nwave wavelengths.
            ivar(numpy.ndarray): Array of (nobj,nwave) inverse-variance values.
            wave(numpy.ndarray): Array of (nwave,) wavelength values in Angstroms. All objects
                are assumed to use the same wavelength grid.
            resolution(numpy.ndarray): Array of (nobj,nres,nwave) resolution matrix elements.
            object_data(numpy.ndarray): Record array of fibermap rows for the objects to add.
            night(str): Date string for the night these objects were observed in the format YYYYMMDD.
            expid(int): Exposure number for these objects.

        Raises:
            RuntimeError: Can only add objects in update mode.
        """
        if self.mode != 'update':
            raise RuntimeError('Can only add objects in update mode.')
        # Augment object_data with constant NIGHT and EXPID columns.
        augmented_data = np.empty(shape = object_data.shape,dtype = self.hdu_list[4].data.dtype)
        for column_def in desispec.io.fibermap.fibermap_columns:
            name = column_def[0]
            if name == 'FILTER' and augmented_data[name].shape != object_data[name].shape:
                for i,filters in enumerate(object_data[name]):
                    augmented_data[name][i] = ','.join(filters)
            else:
                augmented_data[name] = object_data[name]
        augmented_data['NIGHT'] = int(night)
        augmented_data['EXPID'] = expid
        # Concatenate the new per-object image HDU data or use it to initialize the HDU.
        # HDU2 contains the wavelength grid shared by all objects so we only add it once.
        if self.hdu_list[0].data is not None:
            self.hdu_list[0].data = np.concatenate((self.hdu_list[0].data,flux,))
            self.hdu_list[1].data = np.concatenate((self.hdu_list[1].data,ivar,))
            assert np.array_equal(self.hdu_list[2].data,wave),'Wavelength arrays do not match.'
            self.hdu_list[3].data = np.concatenate((self.hdu_list[3].data,resolution,))
        else:
            self.hdu_list[0].data = flux
            self.hdu_list[1].data = ivar
            self.hdu_list[2].data = wave
            self.hdu_list[3].data = resolution
        # Always concatenate our table since a new file will be created with a zero-length table.
        self.hdu_list[4].data = np.concatenate((self.hdu_list[4].data,augmented_data,))

    def get_num_objects(self):
        """
        Get the number of objects contained in this brick file.

        Returns:
            int: Number of objects contained in this brick file.
        """
        return len(self.hdu_list[0].data)

    def close(self):
        """
        Write any updates and close the brick file.
        """
        if self.mode == 'update':
            self.hdu_list.writeto(self.path,clobber = True)
        self.hdu_list.close()
