#!/usr/bin/env python
# encoding: utf-8

from __future__ import print_function, division, absolute_import
import epr
from polymer.block import Block
import numpy as np
from datetime import datetime
from polymer.common import L2FLAGS
import sys
from os.path import basename, join, dirname
from collections import OrderedDict
from polymer.utils import raiseflag
from polymer.level1 import Level1_base

if sys.version_info[:2] >= (3, 0):
    xrange = range

BANDS_MERIS = [412, 443, 490, 510, 560,
               620, 665, 681, 709, 754,
               760, 779, 865, 885, 900]


class Level1_MERIS(Level1_base):

    def __init__(self, filename,
                 sline=0, eline=-1,
                 scol=0, ecol=-1,
                 blocksize=100,
                 dir_smile=None,
                 ancillary=None):

        self.sensor = 'MERIS'
        self.filename = filename
        self.prod = epr.Product(filename)
        self.blocksize = blocksize
        totalwidth = self.prod.get_scene_width()
        totalheight = self.prod.get_scene_height()

        self.init_shape(
                totalheight=totalheight,
                totalwidth=totalwidth,
                sline=sline,
                eline=eline,
                scol=scol,
                ecol=ecol)

        self.full_res = basename(filename).startswith('MER_FR')
        self.ancillary = ancillary

        if dir_smile is None:
            dir_smile = join(dirname(dirname(__file__)), 'auxdata/meris/smile/v2/')

        self.band_names = dict(map(lambda b: (b[1], 'Radiance_{:d}'.format(b[0]+1)),
                                   enumerate(BANDS_MERIS)))

        # initialize solar irradiance
        if self.full_res:
            self.F0 = np.genfromtxt(join(dir_smile, 'sun_spectral_flux_fr.txt'), names=True)
        else:
            self.F0 = np.genfromtxt(join(dir_smile, 'sun_spectral_flux_rr.txt'), names=True)
        self.F0_band_names = dict(map(lambda b: (b[1], 'E0_band{:d}'.format(b[0])),
                                      enumerate(BANDS_MERIS)))

        self.wav_band_names = dict(map(lambda b: (b[1], 'lam_band{:d}'.format(b[0])),
                                       enumerate(BANDS_MERIS)))

        # initialize detector wavelength
        if self.full_res:
            self.detector_wavelength = np.genfromtxt(join(dir_smile, 'central_wavelen_fr.txt'), names=True)
        else:
            self.detector_wavelength = np.genfromtxt(join(dir_smile, 'central_wavelen_rr.txt'), names=True)

        # dates initialization
        self.dstart = self.read_date('SENSING_START')
        self.dstop = self.read_date('SENSING_STOP')
        self.date = self.dstart + (self.dstop - self.dstart)//2

        print('Opened "{}", ({}x{})'.format(filename, self.width, self.height))

        # ancillary data initialization
        self.ancillary_files = OrderedDict()
        if self.ancillary is not None:
            self.init_ancillary()


    def read_date(self, field):
        mph = self.prod.get_mph()
        dat = mph.get_field(field).get_elem(0)
        dat = dat.decode('utf-8')
        dat = dat.replace('-JAN-', '-01-')  # NOTE:
        dat = dat.replace('-FEB-', '-02-')  # parsing with '%d-%b-%Y...' may be
        dat = dat.replace('-MAR-', '-03-')  # locale-dependent
        dat = dat.replace('-APR-', '-04-')
        dat = dat.replace('-MAY-', '-05-')
        dat = dat.replace('-JUN-', '-06-')
        dat = dat.replace('-JUL-', '-07-')
        dat = dat.replace('-AUG-', '-08-')
        dat = dat.replace('-SEP-', '-09-')
        dat = dat.replace('-OCT-', '-10-')
        dat = dat.replace('-NOV-', '-11-')
        dat = dat.replace('-DEC-', '-12-')
        return datetime.strptime(dat, '%d-%m-%Y %H:%M:%S.%f')


    def init_ancillary(self):
        self.ozone = self.ancillary.get('ozone', self.date)
        self.wind_speed = self.ancillary.get('wind_speed', self.date)
        self.surf_press = self.ancillary.get('surf_press', self.date)
        self.ancillary_files.update(self.ozone.filename)
        self.ancillary_files.update(self.wind_speed.filename)
        self.ancillary_files.update(self.surf_press.filename)


    def read_band(self, band_name, size, offset):
        '''
        offset: within the area of interest
        '''
        (ysize, xsize) = size
        (yoffset, xoffset) = offset
        return self.prod.get_band(band_name).read_as_array(
                    xoffset=xoffset+self.scol, yoffset=yoffset+self.sline,
                    width=xsize, height=ysize)


    def read_bitmask(self, size, offset, bmexpr):

        (ysize, xsize) = size
        (yoffset, xoffset) = offset
        raster = epr.create_bitmask_raster(xsize, ysize)
        self.prod.read_bitmask_raster(bmexpr, xoffset+self.scol, yoffset+self.sline, raster)

        return raster.data

    def read_block(self, size, offset, bands):
        '''
        size: size of the block
        offset: offset of the block
        bands: list of bands identifiers
        req: list of identifiers of required datasets
        '''

        (ysize, xsize) = size
        nbands = len(bands)

        # initialize block
        block = Block(offset=offset, size=size, bands=bands)

        block.latitude  = self.read_band('latitude',  size, offset)
        block.longitude = self.read_band('longitude', size, offset)

        # read geometry
        block.sza = self.read_band('sun_zenith', size, offset)
        block.vza = self.read_band('view_zenith', size, offset)
        block.saa = self.read_band('sun_azimuth', size, offset)
        block.vaa = self.read_band('view_azimuth', size, offset)

        # read detector index
        block.detector_index = self.read_band('detector_index', size, offset)

        # get F0 for each band
        block.F0 = np.zeros((ysize, xsize, nbands)) + np.NaN
        for iband, band in enumerate(bands):
            block.F0[:,:,iband] = self.F0[self.F0_band_names[band]][block.detector_index]

        # calculate detector wavelength for each band
        block.wavelen = np.zeros((ysize, xsize, nbands), dtype='float32') + np.NaN
        for iband, band in enumerate(bands):
            block.wavelen[:,:,iband] = self.detector_wavelength[self.wav_band_names[band]][block.detector_index]

        # read TOA
        Ltoa = np.zeros((ysize,xsize,nbands)) + np.NaN
        for iband, band in enumerate(bands):
            Ltoa_ = self.read_band(self.band_names[band], size, offset)
            Ltoa[:,:,iband] = Ltoa_[:,:]
        block.Ltoa = Ltoa

        #
        # read ancillary data
        #
        if self.ancillary is not None:
            block.ozone = self.ozone[block.latitude, block.longitude]
            block.wind_speed = self.wind_speed[block.latitude, block.longitude]
            block.surf_press = self.surf_press[block.latitude, block.longitude]
        else:
            # wind speed (zonal and merdional)
            zwind = self.read_band('zonal_wind', size, offset)
            mwind = self.read_band('merid_wind', size, offset)
            block.wind_speed = np.sqrt(zwind**2 + mwind**2)

            # ozone
            block.ozone = self.read_band('ozone', size, offset)

            # surface pressure
            block.surf_press = self.read_band('atm_press', size, offset)

        # set julian day and month
        block.jday = self.date.timetuple().tm_yday
        block.month = self.date.timetuple().tm_mon

        # read bitmask
        block.bitmask = np.zeros(size, dtype='uint16')
        raiseflag(block.bitmask, L2FLAGS['LAND'],
                  self.read_bitmask(size, offset, 'l1_flags.LAND_OCEAN') != 0)
        raiseflag(block.bitmask, L2FLAGS['L1_INVALID'],
                  self.read_bitmask(size, offset,
                                    '(l1_flags.INVALID) OR (l1_flags.SUSPECT) OR (l1_flags.COSMETIC)') != 0)

        return block


    def blocks(self, bands_read):

        nblocks = int(np.ceil(float(self.height)/self.blocksize))
        for iblock in xrange(nblocks):

            # determine block size
            xsize = self.width
            if iblock == nblocks-1:
                ysize = self.height-(nblocks-1)*self.blocksize
            else:
                ysize = self.blocksize
            size = (ysize, xsize)

            # determine the block offset
            xoffset = 0
            yoffset = iblock*self.blocksize
            offset = (yoffset, xoffset)

            yield self.read_block(size, offset, bands_read)

    def attributes(self, datefmt):
        attr = OrderedDict()
        attr['l1_filename'] = self.filename
        attr['start_time'] = self.dstart.strftime(datefmt)
        attr['stop_time'] = self.dstop.strftime(datefmt)

        attr.update(self.ancillary_files)

        return attr


    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


