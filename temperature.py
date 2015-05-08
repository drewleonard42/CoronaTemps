# -*- coding: utf-8 -*-
"""
Created on Thu Jun  5 15:15:09 2014

@author: drew
"""

from matplotlib import use
use('agg')
import matplotlib.pyplot as plt
from matplotlib import cm, _cm
from matplotlib import patches
import numpy as np
import sunpy
from sunpy.net import vso
from sunpy.map import Map, GenericMap
from sunpy.instr.aia import aiaprep
from scipy.io.idl import readsav as read
from sys import argv, version_info
import os
from os.path import join, exists
from os import system as sys
import datetime as dt
from sunpy.time.timerange import TimeRange as tr
import glob
try:
    from fits import calc_fits
    print 'Fortran extension imported successfully'
except ImportError:
    print 'Current extension is broken, missing or incompatible.\n'\
        +'Compiling Fortran extension.'
    sys('f2py -c -m fits /imaps/holly/home/ajl7/CoronaTemps/fitsmodule.f90')
    from fits import calc_fits
import astropy
import skimage


def gaussian(x, mean=0.0, std=1.0, amp=1.0):
    """Simple function to return a Gaussian distribution"""
    if isinstance(x, list):
        x = np.array(x)
    power = -((x - mean) ** 2.0) / (2.0 * (std ** 2.0))
    f = amp * np.exp(power)
    if amp == 1:
        f = f / max(f)
    return f


def load_temp_responses(n_wlens=6, corrections=True):
    resp = np.zeros((n_wlens, 301))
    tresp = read('/imaps/holly/home/ajl7/CoronaTemps/aia_tresp')
    resp[0, 80:181] = tresp['resp94']
    resp[1, 80:181] = tresp['resp131']
    resp[2, 80:181] = tresp['resp171']
    resp[3, 80:181] = tresp['resp193']
    resp[4, 80:181] = tresp['resp211']
    resp[5, 80:181] = tresp['resp335']
    if n_wlens > 6:
        resp[6, 80:181] = tresp['resp304']
    if corrections:
        # Add empirical correction factor for 9.4nm response function below log(T)=6.3
        # (see Aschwanden et al 2011)
        resp[0:126, 0] = resp[0:126, 0]*6.7
    
    return resp


def find_temp(images, t0=5.6, force_temp_scan=False, maps_dir=None):#home+'temperature_maps/'):
    x, y = images[0].shape
    n_wlens = len(images)
    n_temps = int((7.0 - t0) / 0.01) + 1
    temp = np.arange(t0, 7.01, 0.01)
    
    try:
        if force_temp_scan:
            raise IOError
        model = np.memmap(filename='/imaps/holly/home/ajl7/synth_emiss_1pars', dtype='float32',
                          mode='r', shape=(n_temps, n_wlens))
    except IOError:
        print 'No synthetic emission data found. Re-scanning temperature range.'
        resp = load_temp_responses()
        logt = np.arange(0, 15.05, 0.05)
        # Assume a width of the gaussian DEM distribution and normalise the height
        width = 0.1
        height = 1.0
        delta_t = logt[1] - logt[0]
        model = np.memmap(filename='/imaps/holly/home/ajl7/synth_emiss_1pars', dtype='float32',
                          mode='w+', shape=(n_temps, n_wlens))
        for t, meantemp in enumerate(temp):
            dem = gaussian(logt, meantemp, width, height)
            f = resp * dem
            model[t, :] = np.sum(f, axis=1) * delta_t ### CHECK THIS AXIS!
            normmod = model[t, 2]
            model[t, :] = model[t, :] / normmod
        model.flush()
    ims_array = np.array([im.data for im in images])
    print 'Calculating temperature values...',
    temps, fits = calc_fits(ims_array, model, temp, n_temps, n_wlens, x, y, 1)
    temps[temps == 0] = np.nan
    print 'Done.'
    tempmap = temps[:, :, 0], images[2].meta.copy(), fits
    # TODO: figure out how to change things in the header and save them.
    
    return tempmap


def create_tempmap(date, n_params=1, data_dir=None,
                   maps_dir=None, datfile=None, date_first=True,
                   submap=None):
    wlens = ['094', '131', '171', '193', '211', '335']
    t0 = 5.6
    thiswlen = None
    client = vso.VSOClient()

    if datfile:
        images = {}
        f = open(datfile)
        # Loop through wavelengths
        for line in f:
            if line[:3] in wlens:
                allwlenmaps = []
                thiswlen = line[:3]
                print 'Loading {} files'.format(thiswlen)
            elif 'fits' in line:
                thismap = aiaprep(Map(line[:-1]))
                thismap.data /= thismap.exposure_time
                allwlenmaps.append(thismap)
            elif line.strip() in ['', '\n']:
                if thiswlen:
                    wlenmap = allwlenmaps[-1]
                    for thismap in allwlenmaps[:-1]:
                        wlenmap.data += thismap.data
                    wlenmap.data /= len(allwlenmaps)
                    images[thiswlen] = wlenmap
    
        images = [images[w] for w in wlens]
    else:
        images = []
        imagefiles = []
        for wl, wlen in enumerate(wlens):
            fits_dir = join(data_dir, '{}'.format(wlen))
            filename = join(fits_dir,
                'AIA{0:%Y%m%d}?{0:%H%M}*fits'.format(date))
            filelist = glob.glob(filename)
            if filelist != []:
                imagefiles.append(filelist[0])
                temp_im = Map(filelist[0])
                #temp_im = aiaprep(Map(filelist[0])) # Not necessary, already lvl 1.5
                if submap:
                    temp_im = temp_im.submap(*submap)
                temp_im.data /= temp_im.exposure_time # Can probably increase speed a bit by making this * (1.0/exp_time)
                images.append(temp_im)
            if len(images) < wl+1:
                print 'File not found. Downloading from VSO...'
                qr = client.query(vso.attrs.Time(timerange.start(), timerange.end()),
                                  vso.attrs.Wave(wlen, wlen),
                                  vso.attrs.Instrument('aia'),
                                  vso.attrs.Provider('JSOC'))
                res = client.get(qr, path=join(fits_dir, '{file}'), site='NSO').wait()
                if isinstance(res, list): res = res[0]
                imagefiles.append(res)
                temp_im = aiaprep(Map(res))
                if submap:
                    temp_im = temp_im.submap(*submap)
                temp_im.data /= temp_im.exposure_time # Can probably increase speed a bit by making this * (1.0/exp_time)
                images.append(temp_im)

    # Normalise images to 171A
    normim = images[2].data.copy()
    print 'Normalising images'
    for i in range(len(wlens)):
        images[i].data /= normim
    
    # Produce temperature map
    if n_params == 1:
        tempmap = find_temp(images, t0)
    else:
        pass

    return tempmap


class TemperatureMap(GenericMap):
    def __init__(self, date=None, n_params=1, data_dir=None, maps_dir=None, 
                 fname=None, infofile=None, submap=None):
        if (not fname and not date) or (fname and date):
            print """"You must specify either a date and time for which to create
                temperatures or the name of a file containing a valid 
                TemperatureMap object."""
            return

        if date:
            date = sunpy.time.parse_time(date)
        
            if data_dir is None:
                data_dir = '/media/huw/SDO_data/'
            if maps_dir is None:
                maps_dir='/media/huw/temperature_maps/{}pars/'.format(n_params)
            
            #maps_dir = join(maps_dir, '{:%Y/%m/%d}'.format(date))
            fname = join(maps_dir, '{:%Y-%m-%dT%H_%M_%S}.fits'.format(date))

        if infofile:
            data_dir = None
            maps_dir = open(infofile).readline()[:-1]
            fname = join(maps_dir, '{:%Y-%m-%dT%H:%M:%S}.fits'.format(date))
            fname.replace('/images/', '/data/')

        try:
            newmap = Map(fname)
            GenericMap.__init__(self, newmap.data, newmap.meta)
        except ValueError:
            if n_params == 3:
                pass
            else:
                data, meta, fit = create_tempmap(date, n_params, data_dir, maps_dir, infofile, submap=submap)
                GenericMap.__init__(self, data, meta)
                lowx, highx = (self.xrange[0] / self.scale['x'],
                               self.xrange[1] / self.scale['x'])
                lowy, highy = (self.yrange[0] / self.scale['y'],
                               self.yrange[1] / self.scale['y'])
                x_grid, y_grid = np.mgrid[lowx:highx-1, lowy:highy-1]
                r_grid = np.sqrt((x_grid ** 2.0) + (y_grid ** 2.0))
                outer_rad = (self.rsun_arcseconds * 1.5) / self.scale['x']
                self.data[r_grid > outer_rad] = None

        tmapcubehelix = _cm.cubehelix(s=2.8, r=0.7, h=2.0, gamma=1.0)
        cm.register_cmap(name='temphelix', data=tmapcubehelix)
        self.cmap = cm.get_cmap('temphelix')

        self.meta['date-obs'] = str(date)
        self.data_dir = data_dir
        self.maps_dir = maps_dir
        self.temperature_scale = 'log'
        #self.cmap = cm.coolwarm
        self.region = None
        self.region_coordinate = {'x': 0.0, 'y': 0.0}
        if n_params == 3:
            self.n_params = 3
        else:
            self.n_params = 1

        return
    
    @classmethod
    def is_datasource_for(cls, data, header, **kwargs):
        return header.get('instrume', '').startswith('temperature')
    
    def region_map(self, region, mapsize=300, *args, **kwargs):
        """
        A function to take as input a hek record or similar and create a submap
        showing just the corresponding region
        """
        x, y = region['hpc_coord']
        newmap = self.submap([x-mapsize, x+mapsize], [y-mapsize, y+mapsize],
                            *args, **kwargs)
        
        self.region_coordinate = {'x': x, 'y': y}
        self.region = region

        return newmap
    
    def select_temps(self, mintemp, maxtemp):
        """
        Function to highlight user-defined temperatures
        """
        newdata = np.ones(self.data.shape) * np.NaN
        indices = np.where((self.data > mintemp) * (self.data < maxtemp))
        newdata[indices] = self.data[indices]
        
        return Map(newdata, self.meta.copy())
    
    def convert_scale(self, scale='linear'):
        if self.temperature_scale == scale:
            print "Temperatures are already measured on a {} scale.".format(
                scale)
            return
        elif scale == 'linear':
            self.data = (10.0 ** self.data) / 1.0e6
        elif scale == 'log':
            self.data = np.log10(self.data)
        
        self.temperature_scale = scale
        return
    
    def compare(self, display_wlen='171', context_wlen=None, extra_maps=[]):
        valid_wlens = ['94', '131', '171', '195', '211', '335', '304', 'hmi']
        if display_wlen.lower() not in valid_wlens:
            print "Display wavelength provided invalid or None."
            output = self.plot()#*temp_args, **temp_kwargs)
            return output
        save_output = True
        data_dir = self.data_dir
        maps_dir = self.maps_dir
        
        date = self.date
        nmaps = 2 + len(extra_maps)
        if context_wlen:
            nrows = 2
        else:
            nrows = 1
        
        fig = plt.figure(figsize=(24, 14))
        
        fig.add_subplot(nrows, nmaps, nmaps, axisbg='k')
        self.plot()#*temp_args, **temp_kwargs)
        plt.colorbar(orientation='horizontal')
        
        displaymap = Map(data_dir+'{0}/{1:%Y/%m/%d}/aia*{0}*t{1:%H?%M}*lev1?fits'\
            .format(display_wlen, date))
        if isinstance(displaymap, list):
            displaymap = displaymap[0]
        displaymap = aiaprep(displaymap)
        displaymap /= displaymap.exposure_time
        
        fig.add_subplot(nrows, nmaps, 1, axisbg='k')
        displaymap.plot()#*wlen_args, **wlen_kwargs)
        plt.colorbar(orientation='horizontal')
        
        if context_wlen and self.region != None:
            context_plot = fig.add_subplot(nrows, 1, nrows)
            contextmap = Map(data_dir+'{0}/{1:%Y/%m/%d}/aia*{0}*t{1:%H?%M}*lev1?fits'.format(context_wlen, date))
            if isinstance(contextmap, list):
                contextmap = contextmap[0]
            x, y = self.region_coordinate['x'], self.region_coordinate['y']
            contextmap = contextmap.submap([-1000, 1000], [y-300, y+300])
            # Need to figure out how to get 'subimsize' from self. Use the default 150'' for now
            #rect = patches.Rectangle([x-subdx, y-subdx], subimsize[0], subimsize[1], color='white', fill=False)
            rect = patches.Rectangle([x-150, y-150], 300, 300, color='white',
                                     fill=False)
            contextmap.plot()#*ctxt_args, **ctxt_kwargs)
            context_plot.add_artist(rect)
        
        for m, thismap in extra_maps:
            fig.add_subplot(nrows, nmaps, 3+m)
            thismap.plot()#*extr_args, **extr_kwargs)
        
        if save_output:
            error = os.system('touch '+os.path.join(maps_dir,'maps/{:%Y/%m/%d/} > shelloutput.txt'.format(date)))
            if error != 0:
                os.system('{0}{1:%Y}; {0}{1:%Y/%m}; {0}{1:%Y/%m/%d} > shelloutput.txt'\
                        .format('mkdir '+os.path.join(maps_dir, 'maps/'), date))
            filename = os.path.join(maps_dir,
                'maps/{:%Y/%m/%d/%Y-%m-%dT%H:%M:%S}_with{}'.format(date,
                                                                   display_wlen))
            plt.savefig(filename)
            if self.region != None:
                reg_dir = maps_dir + 'maps/region_maps'
                reg_dir = reg_dir + '/{}/'. format(self.region)
                error = os.system('touch ' + reg_dir + ' > shelloutput.txt')
                if error != 0:
                    os.system('mkdir ' + reg_dir + ' > shelloutput.txt')
                plt.savefig(reg_dir+'{:%Y-%m-%dT%H:%M:%S}'.format(date))
            plt.close()
        else:
            plt.show()

        return
    
    def plot(self, vmin=None, vmax=None, *args, **kwargs):
        mean = np.nanmean(self.data, dtype=np.float64)
        std = np.nanstd(self.data, dtype=np.float64)
        if vmin is None:
            vmin = mean - (2.0 * std)
        if vmax is None:
            vmax = mean + (2.0 * std)
        
        GenericMap.plot(self, vmin=vmin, vmax=vmax, *args, **kwargs)
        
        return
    
    def save(self):#, compress=False):
        date = sunpy.time.parse_time(self.date)
        if not os.path.exists(self.maps_dir):
            os.makedirs(self.maps_dir)
        fname = os.path.join(self.maps_dir,
                             '{:%Y-%m-%dT%H_%M_%S}.fits'.format(date))
        GenericMap.save(self, fname, clobber=True)
        #if compress:
        #    sys("gzip {} -f".format(fname))

    def min(self):
        return np.nanmin(self.data)

    def mean(self):
        return np.nanmean(self.data, dtype='float64')

    def max(self):
        return np.nanmax(self.data)

    def std(self):
        return np.nanstd(self.data, dtype='float64')

    def calculate_density(self, wlen='171', dz=100):
        """
        Calculate an approximation of the coronal average LOS density using a given
        TemperatureMap object and a particular AIA channel.
    
        Parameters
        ----------
        tmap : CoronaTemps.temperature.TemperatureMap
            A TemperatureMap instance containing coronal temperature data
        wlen : {'94' | '131' | '171' | '193' | '211' | '335'}
            AIA wavelength used to approximate the emission measure. '171', '193'
            and '211' are most likely to provide reliable results. Use of other
            channels is not recommended.
        """
        # TODO: Make this a method of the TemperatureMap class
        # Load the appropriate temperature response function
        tresp = read('/imaps/holly/home/ajl7/CoronaTemps/aia_tresp')
        resp = tresp['resp{}'.format(wlen)]
    
        # Get some information from the TemperatureMap and set up filenames, etc
        tempdata = self.data.copy()
        tempdata[np.isnan(tempdata)] = 0.0
        date = sunpy.time.parse_time(self.date)
        data_dir = self.data_dir
        fits_dir = join(data_dir, '{}'.format(wlen))
        filename = join(fits_dir, 'AIA{0:%Y%m%d}?{0:%H%M}*fits'.format(date))
    
        # Load and appropriately process AIA data
        filelist = glob.glob(filename)
        if filelist == []:
            print 'AIA data not found :('
            return
        aiamap = Map(filename)
        aiamap.data /= aiamap.exposure_time
        aiamap = aiaprep(aiamap)
        aiamap = aiamap.submap(self.xrange, self.yrange)
    
        # Create new Map and put density values in it
        nmap = Map(self.data.copy(), self.meta.copy())
        indices = np.round((tempdata - 4.0) / 0.05).astype(int)
        indices[indices < 0] = 0
        indices[indices > 100] = 100
        #nmap.data = np.sqrt(aiamap.data / resp[indices]) / dz
        nmap.data = np.log10(aiamap.data / resp[indices])

        nmapcubehelix = _cm.cubehelix(s=3.0, r=-0.5, h=1.6, gamma=1.0)
        cm.register_cmap(name='denshelix', data=nmapcubehelix)
        nmap.cmap = cm.get_cmap('denshelix')
    
        return nmap


sunpy.map.Map.register(TemperatureMap, TemperatureMap.is_datasource_for)

if __name__ == "__main__":
    date = sunpy.time.parse_time(argv[1])
    infofile = argv[2]    
    tmap = TemperatureMap(date, infofile=infofile)
    tmap.save()
    
    image_dir = open(infofile).readline()[:-1]
    fname = os.path.join(image_dir, '{:%Y-%m-%dT%H_%M_%S}'.format(date))
    print "Temperature map image saved to: {}".format(fname)
    
    fig = plt.figure(16, 12)
    tmap.plot()
    plt.colorbar(orientation='vertical')
    plt.savefig(fname)
    plt.close()
