# nsdfwriter.py --- 
# 
# Filename: nsdfwriter.py
# Description: 
# Author: Subhasis Ray [email: {lastname} dot {firstname} at gmail dot com]
# Maintainer: 
# Created: Fri Apr 25 19:51:42 2014 (+0530)
# Version: 
# Last-Updated: 
#           By: 
#     Update #: 0
# URL: 
# Keywords: 
# Compatibility: 
# 
# 

# Commentary: 
# 
# 
# 
# 

# Change log:
# 
# 
# 
# 
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License as
# published by the Free Software Foundation; either version 3, or
# (at your option) any later version.
# 
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# General Public License for more details.
# 
# You should have received a copy of the GNU General Public License
# along with this program; see the file COPYING.  If not, write to
# the Free Software Foundation, Inc., 51 Franklin Street, Fifth
# Floor, Boston, MA 02110-1301, USA.
# 
# 

# Code:
"""
Writer for NSDF file format.
"""
__author__ = 'Subhasis Ray'
__version__ = '0.1'

import h5py as h5
import numpy as np

from .model import ModelComponent, common_prefix
from .constants import *
from .util import *
from datetime import datetime

def match_datasets(hdfds, pydata):
    """Match entries in hdfds with those in pydata. Returns true if the
    two sets are equal. False otherwise.

    """
    src_set = set([item for item in hdfds])
    dsrc_set = set(pydata)
    return src_set == dsrc_set


def add_model_component(component, parentgroup):
    """Add a model component as a group under `parentgroup`. 

    This creates a group `component.name` under parent group if not
    already present. The `uid` of the component is stored in the `uid`
    attribute of the group. Key-value pairs in the `component.attrs`
    dict are stored as attributes of the group.

    Args: 
        component (ModelComponent): model component object to be
            written to NSDF file.

        parentgroup (HDF Group): group under which this
            component's group should be created.

    Returns:
        HDF Group created for this model component.

    Raises: 
        KeyError if the parentgroup is None and no group
        corresponding to the component's parent exists.

    """
    grp = parentgroup.require_group(component.name)
    component.hdfgroup = grp
    if component.uid is not None:
        grp.attrs['uid'] = component.uid
    else:
        grp.attrs['uid'] = component.path
    for key, value in component.attrs.items():
        grp.attrs[key] = value
    return grp

        
class NSDFWriter(object):
    """Writer for NSDF files.

    An NSDF file has three main groups: `/model`, `/data` and `/map`.

    Attributes: 
        mode (str): File open mode. Defaults to append
            ('a'). Can be 'w' or 'w+' also.

        dialect (nsdf.dialect member): ONED for storing nonuniformly
            sampled and event data in 1D arrays.

            VLEN for storing such data in 2D VLEN datasets.

            NANPADDED for storing such data in 2D homogeneous datasets
            with NaN padding.

        model (h5.Group): /model group

        data (h5.Group): /data group

        mapping (h5.Group): /map group

        time_dim (h5.Group): /map/time group contains the sampling
            time points as dimension scales of data. It is mainly used
            for nonuniformly sampled data.

        modeltree: (h5.Group): '/model/modeltree group can be used for
            storing the model in a hierarchical manner. Each subgroup
            under `modeltree` is a model component and can contain
            other subgroups representing subcomponents. Each group
            stores the unique identifier of the model component it
            represents in the string attribute `uid`.

    """
    def __init__(self, filename, dialect=dialect.ONED, mode='a', **h5args):
        """Initialize NSDF writer.

        Args:

            filename (str): path of the file to be written.

            dialect (nsdf.dialect member): the dialect of NSDF to be
                used. Default: ONED.

            mode (str): file write mode. Default is 'a', which is also
                the default of h5py.File.

            **h5args: other keyword arguments are passed to h5py when
                  creating datasets. These can be `compression`
                  (='gzip'/'szip'/'lzf'), `compression_opts` (=0-9
                  with gzip), `fletcher32` (=True/False), `shuffle`
                  (=True/False).

        """
        self._fd = h5.File(filename, mode)
        self.timestamp = datetime.utcnow()
        self._fd.attrs['timestamp'] = self.timestamp.isoformat()
        self._fd.attrs['version'] = '0.1'
        self.mode = mode
        self.dialect = dialect
        self.data = self._fd.require_group('/data')
        self.model = self._fd.require_group('/model')
        self.mapping = self._fd.require_group('/map')
        self.time_dim = self.mapping.require_group('time')
        self.modeltree = self.model.require_group('modeltree')
        for stype in SAMPLING_TYPES:
            self.data.require_group(stype)
            self.mapping.require_group(stype)
        self.modelroot = ModelComponent('modeltree', uid='modeltree',
                                        hdfgroup=self.modeltree)
        self.h5args = h5args

    def __del__(self):
        self._fd.close()

    def set_title(self, title):
        self._fd.attrs['title'] = title

    def set_creator(self, creator):
        self._fd.attrs['creator'] = creator

    def set_license(self, text):
        self._fd.attrs['license'] = text

    def set_software(self, software_list):       
        self._fd.attrs['software'] = software_list

    def set_method(self, method_list):
        self._fd.attrs['method'] = method_list

    def set_description(self, description):
        self._fd.attrs['description'] = description

    def _link_map_model(self, mapds):
        """Link the model to map dataset and vice versa. 

        The map dataset stores a list of references to the closest
        common ancestor of all the source components in it in the
        attribute `model`. The closest common ancestor in the model
        tree also stores a reference to this map dataset in its `map`
        attribute.

        This is an internal optimization in NSDF because given that
        every model component has an unique id and the map datasets
        store these unique ids, it is always possible to search the
        entire mdoel tree for these unique ids.
    
        Args:
            mapds: The map dataset for which the linking should be done.

        Returns:
            None

        """
        self.modelroot.update_id_path_dict()
        id_path_dict = self.modelroot.get_id_path_dict()
        if mapds.dtype.fields is None:
            idlist = mapds
        else:
            idlist = mapds['source']
            
        if len(id_path_dict) > 1:
            # there are elements other than /model/modeltree
            paths = [id_path_dict[uid] for uid in idlist]
            prefix = common_prefix(paths)[len('/modeltree/'):]
            try:
                source = self.modeltree[prefix]
                tmpattr = ([ref for ref in source.attrs.get('map', [])]
                           + [mapds.ref])
                attr = np.zeros((len(tmpattr),), dtype=REFTYPE)
                attr[:] = tmpattr
                source.attrs['map'] = attr
                tmpattr = ([ref for ref in mapds.attrs.get('map', [])]
                           + [source.ref])
                attr = np.zeros((len(tmpattr),), dtype=REFTYPE)
                attr[:] = tmpattr
                mapds.attrs['model'] = attr                
            except KeyError, error:
                print error.message
        
    def add_modeltree(self, root, target='/'):
        """Add an entire model tree. This will cause the modeltree rooted at
        `root` to be written to the NSDF file.

        Args:
            root (ModelComponent): root of the source tree.

            target (str): target node path in NSDF file with respect
                to '/model/modeltree'. `root` and its children are
                added under this group.

        """
        def write_absolute(node, rootgroup):
            """Write ModelComponent `node` at its path relative to `rootgroup`.
            """
            if node.parent is None:
                parentgroup = rootgroup
            else:
                parentpath = node.parent.path[1:] 
                parentgroup = rootgroup[parentpath]
            add_model_component(node, parentgroup)
            
        node = self.modelroot
        # Get the node corresponding to `target`, traverse by
        # splitting to avoid confusion between absolute and relative
        # paths.
        for name in target.split('/'):
            if name:
                node = node.children[name]
        node.add_child(root)
        self.modelroot.visit(write_absolute, self.model)

    def add_uniform_ds(self, name, idlist):
        """Add the sources listed in idlist under /map/uniform.

        Args: 
            name (str): name with which the datasource list
                should be stored. This will represent a population of
                data sources.

            idlist (list of str): list of unique identifiers of the
                data sources.

        Returns: 
            An HDF5 Dataset storing the source ids. This is
            converted into a dimension scale when actual data is
            added.

        """
        if len(idlist) == 0:
            raise ValueError('idlist must be nonempty')
        base = None
        try:
            base = self.mapping[UNIFORM]
        except KeyError:
            base = self.mapping.create_group(UNIFORM)
        src_ds = base.create_dataset(name, shape=(len(idlist),),
                                 dtype=VLENSTR, data=idlist)
        self._link_map_model(src_ds)
        return src_ds

    def add_nonuniform_ds(self, popname, idlist):
        """Add the sources listed in idlist under /map/nonuniform/{popname}.

        Args: 
            popname (str): name with which the datasource list
                should be stored. This will represent a population of
                data sources.

            idlist (list of str): list of unique identifiers of the
                data sources. This becomes irrelevant if homogeneous=False.

            path_id_dict (dict): (optional) maps the path of the
                source in model tree to the unique id of the source.

        Returns:
            An HDF5 Dataset storing the source ids when dialect
            is VLEN or NANPADDED. This is converted into a dimension
            scale when actual data is added.

        Raises:
            AssertionError if idlist is empty or dialect is ONED.

        """
        base = None
        base = self.mapping.require_group(NONUNIFORM)
        assert self.dialect != dialect.ONED
        assert len(idlist) > 0
        src_ds = base.create_dataset(popname, shape=(len(idlist),),
                                 dtype=VLENSTR, data=idlist)
        self._link_map_model(src_ds)
        return src_ds
    
    def add_nonuniform_ds_1d(self, popname, varname, idlist):
        """Add the sources listed in idlist under
        /map/nonuniform/{popname}/{varname}.

        In case of 1D datasets, for each variable we store the mapping
        from source id to dataset ref in a two column compund dataset
        with dtype=[('source', VLENSTR), ('data', REFTYPE)]

        Args: 
            popname (str): name with which the datasource list
                should be stored. This will represent a population of
                data sources.
            
            varname (str): name of the variable beind recorded. The
                same name should be passed when actual data is being
                added.
        
            idlist (list of str): list of unique identifiers of the
                data sources.

        Returns:
            An HDF5 Dataset storing the source ids in `source` column.

        Raises:
            AssertionError if idlist is empty or if dialect is not ONED.

        """
        base = self.mapping.require_group(NONUNIFORM)
        assert self.dialect == dialect.ONED, 'valid only for dialect=ONED'
        assert len(idlist) > 0, 'idlist must be nonempty'
        grp = base.require_group(popname)
        src_ds = grp.create_dataset(varname, shape=(len(idlist),),
                                dtype=SRCDATAMAPTYPE)
        for iii in range(len(idlist)):
            src_ds[iii] = (idlist[iii], None)
        self._link_map_model(src_ds)
        return src_ds

    def add_event_ds(self, name, idlist):
        """Create a group under `/map/event` with name `name` to store mapping
        between the datasources and event data.

        Args: 
            name (str): name with which the datasource list
                should be stored. This will represent a population of
                data sources.

            idlist (list): (optional) unique ids of the data sources.

        Returns: 
            The HDF5 Group `/map/event/{name}`.

        """
        base = self.mapping.require_group(EVENT)
        assert len(idlist) > 0, 'idlist must be nonempty'
        assert ((self.dialect == dialect.VLEN) or
                (self.dialect == dialect.NANPADDED)),   \
            'only for VLEN or NANPADDED dialects'
        src_ds = base.create_dataset(name, shape=(len(idlist),),
                                 dtype=VLENSTR, data=idlist)
        self._link_map_model(src_ds)
        return src_ds

    def add_event_ds_1d(self, popname, varname, idlist):
        """Create a group under `/map/event` with name `name` to store mapping
        between the datasources and event data.

        Args: 
            name (str): name with which the datasource list
                should be stored. This will represent a population of
                data sources.

            idlist (list): (optional) unique ids of the data sources.

        Returns: 
            The HDF5 Group `/map/event/{name}`.

        """
        base = self.mapping.require_group(EVENT)
        assert len(idlist) > 0, 'idlist must be nonempty'
        assert ((self.dialect == dialect.ONED) or
            (self.dialect == dialect.NUREGULAR)),   \
            'dialect must be ONED or NUREGULAR'
        grp = base.require_group(popname)
        src_ds = grp.create_dataset(varname, shape=(len(idlist),),
                                     dtype=SRCDATAMAPTYPE)
        for iii in range(len(idlist)):
            src_ds[iii] = (idlist[iii], None)
        self._link_map_model(src_ds)
        return src_ds

    def add_static_ds(self, popname, idlist):
        """Add the sources listed in idlist under /map/static.

        Args: 
            name (str): name with which the datasource list
                should be stored. This will represent a population of
                data sources.

            idlist (list of str): list of unique identifiers of the
                data sources.

        Returns: 
            An HDF5 Dataset storing the source ids. This is
            converted into a dimension scale when actual data is
            added.

        """
        if len(idlist) == 0:
            raise ValueError('idlist must be nonempty')
        base = self.mapping.require_group(STATIC)
        src_ds = base.create_dataset(popname, shape=(len(idlist),),
                                 dtype=VLENSTR, data=idlist)
        self.modelroot.update_id_path_dict()
        self._link_map_model(src_ds)
        return src_ds        
    
    def add_uniform_data(self, source_ds, data_object, tstart=0.0,
                         fixed=False):
        """Append uniformly sampled `variable` values from `sources` to
        `data`.

        Args: 
            source_ds (HDF5 Dataset): the dataset storing the source
                ids under map. This is attached to the stored data as
                a dimension scale called `source` on the row
                dimension.

            data_object (nsdf.UniformData): Uniform dataset to be
                added to file.

            tstart (double): (optional) start time of this dataset
                recording. Defaults to 0.
            
            fixed (bool): if True, the data cannot grow. Default: False

        Returns:
            HDF5 dataset storing the data

        Raises:
            KeyError if the sources in `source_data_dict` do not match
            those in `source_ds`.
        
            ValueError if dt is not specified or <= 0 when inserting
            data for the first time.

        """
        popname = source_ds.name.rpartition('/')[-1]
        ugrp = self.data[UNIFORM].require_group(popname)
        if not match_datasets(source_ds, data_object.get_sources()):
            raise KeyError('members of `source_ds` must match sources in'
                           ' `data`.')
        ordered_data = [data_object.get_data(src) for src in source_ds]
        data = np.vstack(ordered_data)
        try:
            dataset = ugrp[data_object.name]
            oldcolcount = dataset.shape[1]
            dataset.resize(oldcolcount + data.shape[1], axis=1)
            dataset[:, oldcolcount:] = data
        except KeyError:
            if data_object.dt <= 0.0:
                raise ValueError('`dt` must be > 0.0 for creating dataset.')
            if data_object.unit is None:
                raise ValueError('`unit` is required for creating dataset.')
            if data_object.tunit is None:
                raise ValueError('`tunit` is required for creating dataset.')
            maxcol = None
            if fixed:
                maxcol = data.shape[1]
            dataset = ugrp.create_dataset(
                data_object.name,
                shape=data.shape,
                dtype=data_object.dtype,
                data=data,
                maxshape=(data.shape[0], maxcol),
                **self.h5args)
            dataset.dims.create_scale(source_ds, 'source')
            dataset.dims[0].attach_scale(source_ds)
            dataset.attrs['tstart'] = tstart
            dataset.attrs['dt'] = data_object.dt
            dataset.attrs['field'] = data_object.field
            dataset.attrs['unit'] = data_object.unit
            dataset.attrs['timeunit'] = data_object.tunit
        return dataset

    def add_nonuniform_regular(self, source_ds, data_object,
                               fixed=False):
        """Append nonuniformly sampled `variable` values from `sources` to
        `data`. In this case sampling times of all the sources are
        same and the data is stored in a 2D dataset.

        Args: 
            source_ds (HDF5 Dataset): the dataset storing the source
                ids under map. This is attached to the stored data as
                a dimension scale called `source` on the row
                dimension.
            
            data_object (nsdf.NonuniformRegularData):
                NonUniformRegular dataset to be added to file.

            fixed (bool): if True, the data cannot grow. Default: False

        Returns:
            HDF5 dataset storing the data

        Raises:
            KeyError if the sources in `data_object` do not match
            those in `source_ds`.
        
            ValueError if the data arrays are not all equal in length.

            ValueError if dt is not specified or <= 0 when inserting
            data for the first time.

        """
        popname = source_ds.name.rpartition('/')[-1]
        ngrp = self.data[NONUNIFORM].require_group(popname)
        if not match_datasets(source_ds, data_object.get_sources()):
            raise KeyError('members of `source_ds` must match sources in'
                           ' `data_object`.')
        ordered_data = [data_object.get_data(src) for src in source_ds]
        data = np.vstack(ordered_data)
        if data.shape[1] != len(data_object.get_times()):
            raise ValueError('number sampling times must be '
                             'same as the number of data points')
        try:
            dataset = ngrp[data_object.name]
            oldcolcount = dataset.shape[1]
            dataset.resize(oldcolcount + data.shape[1], axis=1)
            dataset[:, oldcolcount:] = data
        except KeyError:
            if data_object.unit is None:
                raise ValueError('`unit` is required for creating dataset.')
            if data_object.tunit is None:
                raise ValueError('`tunit` is required for creating dataset.')
            maxcol = None
            if fixed:
                maxcol = data.shape[1]
            dataset = ngrp.create_dataset(
                data_object.name, shape=data.shape,
                dtype=data.dtype,
                data=data,
                maxshape=(data.shape[0], maxcol),
                **self.h5args)
            dataset.dims.create_scale(source_ds, 'source')
            dataset.dims[0].attach_scale(source_ds)
            dataset.attrs['field'] = data_object.field
            dataset.attrs['unit'] = data_object.unit
            tsname = '{}_{}'.format(popname, data_object.name)
            tscale = self.time_dim.create_dataset(
                tsname,
                shape=(len(data_object.get_times()),),
                dtype=np.float64,
                data=data_object.get_times(),
                **self.h5args)
            dataset.dims.create_scale(tscale, 'time')
            dataset.dims[1].label = 'time'
            dataset.dims[1].attach_scale(tscale)
            tscale.attrs['unit'] = data_object.tunit
        return dataset

    def add_nonuniform_1d(self, source_ds, data_object,
                          source_name_dict, fixed=False):
        """Add nonuniform data when data from each source is in a separate 1D
        dataset.

        For a population of sources called {population}, a group
        `/map/nonuniform/{population}` must be first created (using
        add_nonuniform_ds). This is passed as `source_ds` argument.
        
        When adding the data, the uid of the sources and the names for
        the corresponding datasets must be specified and this function
        will create one dataset for each source under
        `/data/nonuniform/{population}/{name}` where {name} is the
        name of the data_object, preferably the name of the field
        being recorded.
        
        This function can be used when different sources in a
        population are sampled at different time points for a field
        value. Such case may arise when each member of the population
        is simulated using a variable timestep method like CVODE and
        this timestep is not global.

        Args: 
            source_ds (HDF5 dataset): the dataset
                `/map/nonuniform/{population}/{variable}` created for
                this population of sources (created by
                add_nonunifrom_ds_1d).

            data_object (nsdf.NonuniformData): NSDFData object storing
                the data for all sources in `source_ds`.

            source_name_dict (dict): mapping from source id to dataset
                name.

            fixed (bool): if True, the data cannot grow. Default:
                False

        Returns:
            dict mapping source ids to the tuple (dataset, time).

        Raises:
            AssertionError when dialect is not ONED.

        """
        assert self.dialect == dialect.ONED, \
            'add 1D dataset under nonuniform only for dialect=ONED'
        popname = source_ds.name.split('/')[-2]
        ngrp = self.data[NONUNIFORM].require_group(popname)
        assert match_datasets(source_name_dict.keys(),
                              data_object.get_sources()), \
               'sources in `source_name_dict`'    \
               ' do not match those in `data_object`'
        assert match_datasets(source_ds['source'],
                              source_name_dict.keys()),  \
            'sources in mapping dataset do not match those with data'
        datagrp = ngrp.require_group(data_object.name)
        datagrp.attrs['source'] = source_ds.ref
        ret = {}
        for iii, source in enumerate(source_ds['source']):
            data, time = data_object.get_data(source)
            dsetname = source_name_dict[source]
            timescale = None
            try:
                dset = datagrp[dsetname]
                oldlen = dset.shape[0]
                timescale = dset.dims[0]['time']
                dset.resize((oldlen + len(data),))
                dset[oldlen:] = data
                timescale.resize((oldlen + len(data),))
                timescale[oldlen:] = time
            except KeyError:
                if data_object.unit is None:
                    raise ValueError('`unit` is required'
                                     ' for creating dataset.')
                if data_object.tunit is None:
                    raise ValueError('`tunit` is required'
                                     ' for creating dataset.')
                maxcol = len(data) if fixed else None
                dset = datagrp.create_dataset(
                    dsetname,
                    shape=(len(data),),
                    dtype=data_object.dtype,
                    data=data,
                    maxshape=(maxcol,),
                    **self.h5args)
                dset.attrs['unit'] = data_object.unit
                dset.attrs['field'] = data_object.field
                dset.attrs['source'] = source
                source_ds[iii] = (source, dset.ref)
                # Using {popname}_{variablename}_{dsetname} for
                # simplicity. What about creating a hierarchy?
                tsname = '{}_{}_{}'.format(popname, data_object.name, dsetname)
                timescale = self.time_dim.create_dataset(
                    tsname,
                    shape=(len(data),),
                    dtype=np.float64,
                    data=time,
                    maxshape=(maxcol,),
                    **self.h5args)
                dset.dims.create_scale(timescale, 'time')
                dset.dims[0].label = 'time'
                dset.dims[0].attach_scale(timescale)
                timescale.attrs['unit'] = data_object.tunit
            ret[source] = (dset, timescale)
        return ret
    
    def add_nonuniform_vlen(self, source_ds, data_object,
                                fixed=False):
        """Add nonuniform data when data from all sources in a population is
        stored in a 2D ragged array.

        When adding the data, the uid of the sources and the names for
        the corresponding datasets must be specified and this function
        will create the dataset `/data/nonuniform/{population}/{name}`
        where {name} is the first argument, preferably the name of the
        field being recorded.
        
        This function can be used when different sources in a
        population are sampled at different time points for a field
        value. Such case may arise when each member of the population
        is simulated using a variable timestep method like CVODE and
        this timestep is not global.

        Args: 
            source_ds (HDF5 dataset): the dataset under
                `/map/nonuniform` created for this population of
                sources (created by add_nonunifrom_ds).

            data_object (nsdf.NonuniformData): NSDFData object storing
                the data for all sources in `source_ds`.

            fixed (bool): if True, this is a one-time write and the
                data cannot grow. Default: False

        Returns:
            tuple containing HDF5 Datasets for the data and sampling
            times.

        TODO: 
            Concatenating old data with new data and reassigning is a poor
            choice. waiting for response from h5py mailing list about
            appending data to rows of vlen datasets. If that is not
            possible, vlen dataset is a technically poor choice.

            h5py does not support vlen datasets with float64
            elements. Change dtype to np.float64 once that is
            developed.

        """
        if self.dialect != dialect.VLEN:
            raise Exception('add 2D vlen dataset under nonuniform'
                            ' only for dialect=VLEN')
        popname = source_ds.name.rpartition('/')[-1]
        ngrp = self.data[NONUNIFORM].require_group(popname)
        if not match_datasets(source_ds, data_object.get_sources()):
            raise KeyError('members of `source_ds` must match keys of'
                           ' `source_data_dict`.')
        # Using {popname}_{variablename} for simplicity. What
        # about creating a hierarchy?
        tsname = '{}_{}'.format(popname, data_object.name)
        try:
            dataset = ngrp[data_object.name]
            time_ds = self.time_dim[tsname]
        except KeyError:
            if data_object.unit is None:
                raise ValueError('`unit` is required for creating dataset.')
            if data_object.tunit is None:
                raise ValueError('`tunit` is required for creating dataset.')
            vlentype = h5.special_dtype(vlen=data_object.dtype)
            maxrows = source_ds.shape[0] if fixed else None
            # Fix me: is there any point of keeping the compression
            # and shuffle options?
            dataset = ngrp.create_dataset(
                data_object.name,
                shape=source_ds.shape,
                dtype=vlentype,
                **self.h5args)
            dataset.attrs['field'] = data_object.field
            dataset.attrs['unit'] = data_object.unit
            dataset.dims.create_scale(source_ds, 'source')
            dataset.dims[0].attach_scale(source_ds)
            # FIXME: VLENFLOAT should be made VLENDOUBLE whenever h5py
            # fixes it
            time_ds = self.time_dim.create_dataset(
                tsname,
                shape=dataset.shape,
                maxshape=(maxrows,),
                dtype=VLENFLOAT,
                **self.h5args)
            dataset.dims.create_scale(time_ds, 'time')
            dataset.dims[0].attach_scale(time_ds)
            time_ds.attrs['unit'] = data_object.tunit
        for iii, source in enumerate(source_ds):
            data, time, = data_object.get_data(source)
            dataset[iii] = np.concatenate((dataset[iii], data))
            time_ds[iii] = np.concatenate((time_ds[iii], time))
        return dataset, time_ds

    def add_nonuniform_nan(self, source_ds, data_object, fixed=False):
        """Add nonuniform data when data from all sources in a population is
        stored in a 2D array with NaN padding.

        Args: 
            source_ds (HDF5 Dataset): the dataset under
                `/map/event` created for this population of
                sources (created by add_nonunifrom_ds).

            data_object (nsdf.EventData): NSDFData object storing
                the data for all sources in `source_ds`.

            fixed (bool): if True, this is a one-time write and the
                data cannot grow. Default: False

        Returns:
            HDF5 Dataset containing the data.

        Notes: 
            Concatenating old data with new data and reassigning is a
            poor choice for saving data incrementally. HDF5 does not
            seem to support appending data to VLEN datasets.

            h5py does not support vlen datasets with float64
            elements. Change dtype to np.float64 once that is
            developed.

        """
        assert self.dialect == dialect.NANPADDED,    \
            'add 2D dataset under `nonuniform` only for dialect=NANPADDED'
        popname = source_ds.name.rpartition('/')[-1]
        ngrp = self.data[NONUNIFORM].require_group(popname)
        if not match_datasets(source_ds, data_object.get_sources()):
            raise KeyError('members of `source_ds` must match sources '
                           'in `data_object`.')
        # Using {popname}_{variablename} for simplicity. What
        # about creating a hierarchy?
        tsname = '{}_{}'.format(popname, data_object.name)
        cols = [len(data_object.get_data(source)[0]) for source in
                source_ds]
        starts = np.zeros(source_ds.shape[0], dtype=int)
        ends = np.asarray(cols, dtype=int)
        try:
            dataset = ngrp[data_object.name]
            for iii in range(source_ds.shape[0]):
                try:
                    starts[iii] = next(find(dataset[iii], np.isnan))[0][0]
                except StopIteration:
                    starts[iii] = len(dataset[iii])
                ends[iii] = starts[iii] + cols[iii]
            dataset.resize(max(ends), 1)            
            time_ds = self.time_dim[tsname]
            time_ds.resize(max(ends), 1)
        except KeyError:
            if data_object.unit is None:
                raise ValueError('`unit` is required for creating dataset.')
            if data_object.tunit is None:
                raise ValueError('`tunit` is required for creating dataset.')
            
            maxrows = len(source_ds) if fixed else None
            maxcols = max(cols) if fixed else None
            dataset = ngrp.create_dataset(
                data_object.name,
                shape=(source_ds.shape[0], max(ends)),
                maxshape=(maxrows, maxcols),
                fillvalue=np.nan,
                dtype=data_object.dtype,
                **self.h5args)
            dataset.attrs['field'] = data_object.field
            dataset.attrs['unit'] = data_object.unit
            dataset.dims.create_scale(source_ds, 'source')
            dataset.dims[0].attach_scale(source_ds)
            time_ds = self.time_dim.create_dataset(
                tsname,
                shape=dataset.shape,
                maxshape=(maxrows,maxcols),
                dtype=np.float64,
                fillvalue=np.nan,
                **self.h5args)
            dataset.dims.create_scale(time_ds, 'time')
            dataset.dims[1].attach_scale(time_ds)
            time_ds.attrs['unit'] = data_object.tunit
        for iii, source in enumerate(source_ds):
            data, time = data_object.get_data(source)
            dataset[iii, starts[iii]:ends[iii]] = data
            time_ds[iii, starts[iii]:ends[iii]] = time
        return dataset


    def add_event_1d(self, source_ds, data_object, source_name_dict,
                     fixed=False):
        """Add event time data when data from each source is in a separate 1D
        dataset.

        For a population of sources called {population}, a group
        `/map/event/{population}` must be first created (using
        add_event_ds). This is passed as `source_ds` argument.
        
        When adding the data, the uid of the sources and the names for
        the corresponding datasets must be specified in
        `source_name_dict` and this function will create one dataset
        for each source under `/data/event/{population}/{name}` where
        {name} is the name of the data_object, preferably the field
        name.
        
        Args: 
            source_ds (HDF5 Dataset): the dataset
                `/map/event/{populationname}{variablename}` created
                for this population of sources (created by
                add_event_ds_1d). The name of this group reflects
                that of the group under `/data/event` which stores the
                datasets.

            data_object (nsdf.EventData): NSDFData object storing
                the data for all sources in `source_ds`.

            source_name_dict (dict): mapping from source id to dataset
                name.

            fixed (bool): if True, the data cannot grow. Default:
                False

        Returns:
            dict mapping source ids to datasets.

        """
        assert ((self.dialect == dialect.ONED) or
            self.dialect == dialect.NUREGULAR), \
            'add 1D dataset under event only for dialect=ONED or NUREGULAR'
        popname = source_ds.name.split('/')[-2]
        ngrp = self.data[EVENT].require_group(popname)
        assert match_datasets(source_name_dict.keys(),
                              data_object.get_sources()),  \
            'number of sources do not match number of datasets'
        datagrp = ngrp.require_group(data_object.name)
        datagrp.attrs['source'] = source_ds.ref
        ret = {}
        for iii, source in enumerate(source_ds['source']):
            data = data_object.get_data(source)
            dsetname = source_name_dict[source]
            try:
                dset = datagrp[dsetname]
                oldlen = dset.shape[0]
                dset.resize((oldlen + len(data),))
                dset[oldlen:] = data
            except KeyError:
                if data_object.unit is None:
                    raise ValueError('`unit` is required for creating dataset.')
                maxrows = len(data) if fixed else None
                dset = datagrp.create_dataset(
                    dsetname,
                    shape=(len(data),),
                    dtype=data_object.dtype, data=data,
                    maxshape=(maxrows,),
                    **self.h5args)
                dset.attrs['unit'] = data_object.unit
                dset.attrs['field'] = data_object.field
                dset.attrs['source'] = source
                source_ds[iii] = (source, dset.ref)
            ret[source] = dset
        return ret
    
    def add_event_vlen(self, source_ds, data_object, fixed=False):
        """Add event data when data from all sources in a population is
        stored in a 2D ragged array.

        When adding the data, the uid of the sources and the names for
        the corresponding datasets must be specified and this function
        will create the dataset `/data/event/{population}/{name}`
        where {name} is name of the data_object, preferably the name
        of the field being recorded.
        
        Args: 
            source_ds (HDF5 Dataset): the dataset under
                `/map/event` created for this population of
                sources (created by add_nonunifrom_ds).

            data_object (nsdf.EventData): NSDFData object storing
                the data for all sources in `source_ds`.

            fixed (bool): if True, this is a one-time write and the
                data cannot grow. Default: False

        Returns:
            HDF5 Dataset containing the data.

        Notes: 
            Concatenating old data with new data and reassigning is a
            poor choice for saving data incrementally. HDF5 does not
            seem to support appending data to VLEN datasets.

            h5py does not support vlen datasets with float64
            elements. Change dtype to np.float64 once that is
            developed.

        """
        if self.dialect != dialect.VLEN:
            raise Exception('add 2D vlen dataset under event'
                            ' only for dialect=VLEN')
        popname = source_ds.name.rpartition('/')[-1]
        ngrp = self.data[EVENT].require_group(popname)
        if not match_datasets(source_ds, data_object.get_sources()):
            raise KeyError('members of `source_ds` must match sources '
                           'in `data_object`.')        
        try:
            dataset = ngrp[data_object.name]
        except KeyError:
            if data_object.unit is None:
                raise ValueError('`unit` is required for creating dataset.')
            vlentype = h5.special_dtype(vlen=data_object.dtype)
            maxrows = len(source_ds) if fixed else None
            # Fix me: is there any point of keeping the compression
            # and shuffle options?
            dataset = ngrp.create_dataset(
                data_object.name, shape=source_ds.shape,
                maxshape=(maxrows,),
                dtype=vlentype,
                **self.h5args)
            dataset.attrs['field'] = data_object.field
            dataset.attrs['unit'] = data_object.unit
            dataset.dims.create_scale(source_ds, 'source')
            dataset.dims[0].attach_scale(source_ds)
        for iii, source in enumerate(source_ds):
            data = data_object.get_data(source)
            dataset[iii] = np.concatenate((dataset[iii], data))
        return dataset

    def add_event_nan(self, source_ds, data_object, fixed=False):
        """Add event data when data from all sources in a population is
        stored in a 2D array with NaN padding.

        Args: 
            source_ds (HDF5 Dataset): the dataset under
                `/map/event` created for this population of
                sources (created by add_nonunifrom_ds).

            data_object (nsdf.EventData): NSDFData object storing
                the data for all sources in `source_ds`.

            fixed (bool): if True, this is a one-time write and the
                data cannot grow. Default: False

        Returns:
            HDF5 Dataset containing the data.

        """
        assert self.dialect == dialect.NANPADDED,    \
            'add 2D vlen dataset under event only for dialect=NANPADDED'
        popname = source_ds.name.rpartition('/')[-1]
        ngrp = self.data[EVENT].require_group(popname)
        if not match_datasets(source_ds, data_object.get_sources()):
            raise KeyError('members of `source_ds` must match sources '
                           'in `data_object`.')
        cols = [len(data_object.get_data(source)) for source in
                source_ds]
        starts = np.zeros(source_ds.shape[0], dtype=int)
        ends = np.asarray(cols, dtype=int)
        try:
            dataset = ngrp[data_object.name]
            for iii in range(dataset.shape[0]):
                try:
                    starts[iii] = next(find(dataset[iii], np.isnan))[0][0]
                except StopIteration:
                    starts[iii] = len(dataset[iii])
                ends[iii] = starts[iii] + cols[iii]
            dataset.resize(max(ends), 1)            
        except KeyError:
            if data_object.unit is None:
                raise ValueError('`unit` is required for creating dataset.')
            maxrows = len(source_ds) if fixed else None
            maxcols = max(ends) if fixed else None
            dataset = ngrp.create_dataset(
                data_object.name,
                shape=(source_ds.shape[0], max(ends)),
                maxshape=(maxrows, maxcols),
                dtype=data_object.dtype,
                fillvalue=np.nan,
                **self.h5args)
            dataset.attrs['field'] = data_object.field
            dataset.attrs['unit'] = data_object.unit
            dataset.dims.create_scale(source_ds, 'source')
            dataset.dims[0].attach_scale(source_ds)
        for iii, source in enumerate(source_ds):
            data = data_object.get_data(source)
            dataset[iii, starts[iii]:ends[iii]] = data
        return dataset
    
    def add_static_data(self, source_ds, data_object,
                        fixed=True):
        """Append static data `variable` values from `sources` to `data`.

        Args: 
           source_ds (HDF5 Dataset): the dataset storing the source
                ids under map. This is attached to the stored data as
                a dimension scale called `source` on the row
                dimension.

            data_object (nsdf.EventData): NSDFData object storing
                the data for all sources in `source_ds`.
            
            fixed (bool): if True, the data cannot grow. Default: True

        Returns:
            HDF5 dataset storing the data

        Raises:
            KeyError if the sources in `source_data_dict` do not match
            those in `source_ds`.
        
        """
        popname = source_ds.name.rpartition('/')[-1]
        ugrp = self.data[STATIC].require_group(popname)
        if not match_datasets(source_ds, data_object.get_sources()):
            raise KeyError('members of `source_ds` must match keys of'
                           ' `source_data_dict`.')
        ordered_data = [data_object.get_data( src) for src in    \
                        source_ds]
        data = np.vstack(ordered_data)
        try:
            dataset = ugrp[data_object.name]
            oldcolcount = dataset.shape[1]
            dataset.resize(oldcolcount + data.shape[1], axis=1)
            dataset[:, oldcolcount:] = data
        except KeyError:
            if data_object.unit is None:
                raise ValueError('`unit` is required for creating dataset.')
            maxcol = None
            if fixed:
                maxcol = data.shape[1]
            dataset = ugrp.create_dataset(
                data_object.name, shape=data.shape,
                dtype=data_object.dtype,
                data=data,
                maxshape=(data.shape[0], maxcol),
                **self.h5args)
            dataset.dims.create_scale(source_ds, 'source')
            dataset.dims[0].attach_scale(source_ds)
            dataset.attrs['field'] = data_object.field
            dataset.attrs['unit'] = data_object.unit
        return dataset

    
# 
# nsdfwriter.py ends here