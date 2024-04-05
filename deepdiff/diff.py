#!/usr/bin/env python

# In order to run the docstrings:
# python3 -m deepdiff.diff
# You might need to run it many times since dictionaries come in different orders
# every time you run the docstrings.
# However the docstring expects it in a specific order in order to pass!
import difflib
import logging
import types
from enum import Enum
from copy import deepcopy
from math import isclose as is_close
from collections.abc import Mapping, Iterable, Sequence
from collections import defaultdict
from inspect import getmembers
from itertools import zip_longest
from ordered_set import OrderedSet
from deepdiff.helper import (strings, bytes_type, numbers, uuids, datetimes, ListItemRemovedOrAdded, notpresent,
                             IndexedHash, unprocessed, add_to_frozen_set, basic_types,
                             convert_item_or_items_into_set_else_none, get_type,
                             convert_item_or_items_into_compiled_regexes_else_none,
                             type_is_subclass_of_type_group, type_in_type_group, get_doc,
                             number_to_string, datetime_normalize, KEY_TO_VAL_STR, booleans,
                             np_ndarray, np_floating, get_numpy_ndarray_rows, OrderedSetPlus, RepeatedTimer,
                             TEXT_VIEW, TREE_VIEW, DELTA_VIEW, detailed__dict__, add_root_to_paths,
                             np, get_truncate_datetime, dict_, CannotCompare, ENUM_INCLUDE_KEYS,
                             PydanticBaseModel, Opcode,)
from deepdiff.serialization import SerializationMixin
from deepdiff.distance import DistanceMixin
from deepdiff.model import (
    RemapDict, ResultDict, TextResult, TreeResult, DiffLevel,
    DictRelationship, AttributeRelationship, REPORT_KEYS,
    SubscriptableIterableRelationship, NonSubscriptableIterableRelationship,
    SetRelationship, NumpyArrayRelationship, CUSTOM_FIELD, PrettyOrderedSet,
    FORCE_DEFAULT,
)
from deepdiff.deephash import DeepHash, combine_hashes_lists
from deepdiff.base import Base
from deepdiff.lfucache import LFUCache, DummyLFU

logger = logging.getLogger(__name__)

MAX_PASSES_REACHED_MSG = (
    'DeepDiff has reached the max number of passes of {}. '
    'You can possibly get more accurate results by increasing the max_passes parameter.')

MAX_DIFFS_REACHED_MSG = (
    'DeepDiff has reached the max number of diffs of {}. '
    'You can possibly get more accurate results by increasing the max_diffs parameter.')


notpresent_indexed = IndexedHash(indexes=[0], item=notpresent)

doc = get_doc('diff_doc.rst')


PROGRESS_MSG = "DeepDiff {} seconds in progress. Pass #{}, Diff #{}"


def _report_progress(_stats, progress_logger, duration):
    """
    Report the progress every few seconds.
    """
    progress_logger(PROGRESS_MSG.format(duration, _stats[PASSES_COUNT], _stats[DIFF_COUNT]))


DISTANCE_CACHE_HIT_COUNT = 'DISTANCE CACHE HIT COUNT'
DIFF_COUNT = 'DIFF COUNT'
PASSES_COUNT = 'PASSES COUNT'
MAX_PASS_LIMIT_REACHED = 'MAX PASS LIMIT REACHED'
MAX_DIFF_LIMIT_REACHED = 'MAX DIFF LIMIT REACHED'
DISTANCE_CACHE_ENABLED = 'DISTANCE CACHE ENABLED'
PREVIOUS_DIFF_COUNT = 'PREVIOUS DIFF COUNT'
PREVIOUS_DISTANCE_CACHE_HIT_COUNT = 'PREVIOUS DISTANCE CACHE HIT COUNT'
CANT_FIND_NUMPY_MSG = 'Unable to import numpy. This must be a bug in DeepDiff since a numpy array is detected.'
INVALID_VIEW_MSG = 'The only valid values for the view parameter are text and tree. But {} was passed.'
CUTOFF_RANGE_ERROR_MSG = 'cutoff_distance_for_pairs needs to be a positive float max 1.'
VERBOSE_LEVEL_RANGE_MSG = 'verbose_level should be 0, 1, or 2.'
PURGE_LEVEL_RANGE_MSG = 'cache_purge_level should be 0, 1, or 2.'
_ENABLE_CACHE_EVERY_X_DIFF = '_ENABLE_CACHE_EVERY_X_DIFF'

# What is the threshold to consider 2 items to be pairs. Only used when ignore_order = True.
CUTOFF_DISTANCE_FOR_PAIRS_DEFAULT = 0.3

# What is the threshold to calculate pairs of items between 2 iterables.
# For example 2 iterables that have nothing in common, do not need their pairs to be calculated.
CUTOFF_INTERSECTION_FOR_PAIRS_DEFAULT = 0.7

DEEPHASH_PARAM_KEYS = (
    'exclude_types',
    'exclude_paths',
    'include_paths',
    'exclude_regex_paths',
    'hasher',
    'significant_digits',
    'number_format_notation',
    'ignore_string_type_changes',
    'ignore_numeric_type_changes',
    'ignore_type_in_groups',
    'ignore_type_subclasses',
    'ignore_string_case',
    'exclude_obj_callback',
    'ignore_private_variables',
    'encodings',
    'ignore_encoding_errors',
)


class DeepDiff(ResultDict, SerializationMixin, DistanceMixin, Base):
    __doc__ = doc

    CACHE_AUTO_ADJUST_THRESHOLD = 0.25

    def __init__(self,
                 t1,
                 t2,
                 cache_purge_level=1,
                 cache_size=0,
                 cache_tuning_sample_size=0,
                 custom_operators=None,
                 cutoff_distance_for_pairs=CUTOFF_DISTANCE_FOR_PAIRS_DEFAULT,
                 cutoff_intersection_for_pairs=CUTOFF_INTERSECTION_FOR_PAIRS_DEFAULT,
                 encodings=None,
                 exclude_obj_callback=None,
                 exclude_obj_callback_strict=None,
                 exclude_paths=None,
                 include_obj_callback=None,
                 include_obj_callback_strict=None,
                 include_paths=None,
                 exclude_regex_paths=None,
                 exclude_types=None,
                 get_deep_distance=False,
                 group_by=None,
                 group_by_sort_key=None,
                 hasher=None,
                 hashes=None,
                 ignore_encoding_errors=False,
                 ignore_nan_inequality=False,
                 ignore_numeric_type_changes=False,
                 ignore_order=False,
                 ignore_order_func=None,
                 ignore_private_variables=True,
                 ignore_string_case=False,
                 ignore_string_type_changes=False,
                 ignore_type_in_groups=None,
                 ignore_type_subclasses=False,
                 iterable_compare_func=None,
                 zip_ordered_iterables=False,
                 log_frequency_in_sec=0,
                 math_epsilon=None,
                 max_diffs=None,
                 max_passes=10000000,
                 number_format_notation="f",
                 number_to_string_func=None,
                 progress_logger=logger.info,
                 report_repetition=False,
                 significant_digits=None,
                 truncate_datetime=None,
                 verbose_level=1,
                 view=TEXT_VIEW,
                 _original_type=None,
                 _parameters=None,
                 _shared_parameters=None,
                 **kwargs):
        super().__init__()
        if kwargs:
            raise ValueError((
                "The following parameter(s) are not valid: %s\n"
                "The valid parameters are ignore_order, report_repetition, significant_digits, "
                "number_format_notation, exclude_paths, include_paths, exclude_types, exclude_regex_paths, ignore_type_in_groups, "
                "ignore_string_type_changes, ignore_numeric_type_changes, ignore_type_subclasses, truncate_datetime, "
                "ignore_private_variables, ignore_nan_inequality, number_to_string_func, verbose_level, "
                "view, hasher, hashes, max_passes, max_diffs, zip_ordered_iterables, "
                "cutoff_distance_for_pairs, cutoff_intersection_for_pairs, log_frequency_in_sec, cache_size, "
                "cache_tuning_sample_size, get_deep_distance, group_by, group_by_sort_key, cache_purge_level, "
                "math_epsilon, iterable_compare_func, _original_type, "
                "ignore_order_func, custom_operators, encodings, ignore_encoding_errors, "
                "_parameters and _shared_parameters.") % ', '.join(kwargs.keys()))

        if _parameters:
            self.__dict__.update(_parameters)
        else:
            self.custom_operators = custom_operators or []
            self.ignore_order = ignore_order

            self.ignore_order_func = ignore_order_func

            ignore_type_in_groups = ignore_type_in_groups or []
            if numbers == ignore_type_in_groups or numbers in ignore_type_in_groups:
                ignore_numeric_type_changes = True
            self.ignore_numeric_type_changes = ignore_numeric_type_changes
            if strings == ignore_type_in_groups or strings in ignore_type_in_groups:
                ignore_string_type_changes = True
            self.ignore_string_type_changes = ignore_string_type_changes
            self.ignore_type_in_groups = self.get_ignore_types_in_groups(
                ignore_type_in_groups=ignore_type_in_groups,
                ignore_string_type_changes=ignore_string_type_changes,
                ignore_numeric_type_changes=ignore_numeric_type_changes,
                ignore_type_subclasses=ignore_type_subclasses)
            self.report_repetition = report_repetition
            self.exclude_paths = add_root_to_paths(convert_item_or_items_into_set_else_none(exclude_paths))
            self.include_paths = add_root_to_paths(convert_item_or_items_into_set_else_none(include_paths))
            self.exclude_regex_paths = convert_item_or_items_into_compiled_regexes_else_none(exclude_regex_paths)
            self.exclude_types = set(exclude_types) if exclude_types else None
            self.exclude_types_tuple = tuple(exclude_types) if exclude_types else None  # we need tuple for checking isinstance
            self.ignore_type_subclasses = ignore_type_subclasses
            self.type_check_func = type_in_type_group if ignore_type_subclasses else type_is_subclass_of_type_group
            self.ignore_string_case = ignore_string_case
            self.exclude_obj_callback = exclude_obj_callback
            self.exclude_obj_callback_strict = exclude_obj_callback_strict
            self.include_obj_callback = include_obj_callback
            self.include_obj_callback_strict = include_obj_callback_strict
            self.number_to_string = number_to_string_func or number_to_string
            self.iterable_compare_func = iterable_compare_func
            self.zip_ordered_iterables = zip_ordered_iterables
            self.ignore_private_variables = ignore_private_variables
            self.ignore_nan_inequality = ignore_nan_inequality
            self.hasher = hasher
            self.cache_tuning_sample_size = cache_tuning_sample_size
            self.group_by = group_by
            if callable(group_by_sort_key):
                self.group_by_sort_key = group_by_sort_key
            elif group_by_sort_key:
                def _group_by_sort_key(x):
                    return x[group_by_sort_key]
                self.group_by_sort_key = _group_by_sort_key
            else:
                self.group_by_sort_key = None
            self.encodings = encodings
            self.ignore_encoding_errors = ignore_encoding_errors

            self.significant_digits = self.get_significant_digits(significant_digits, ignore_numeric_type_changes)
            self.math_epsilon = math_epsilon
            if self.math_epsilon is not None and self.ignore_order:
                logger.warning("math_epsilon in conjunction with ignore_order=True is only used for flat object comparisons. Custom math_epsilon will not have an effect when comparing nested objects.")
            self.truncate_datetime = get_truncate_datetime(truncate_datetime)
            self.number_format_notation = number_format_notation
            if verbose_level in {0, 1, 2}:
                self.verbose_level = verbose_level
            else:
                raise ValueError(VERBOSE_LEVEL_RANGE_MSG)
            if cache_purge_level not in {0, 1, 2}:
                raise ValueError(PURGE_LEVEL_RANGE_MSG)
            self.view = view
            # Setting up the cache for dynamic programming. One dictionary per instance of root of DeepDiff running.
            self.max_passes = max_passes
            self.max_diffs = max_diffs
            self.cutoff_distance_for_pairs = float(cutoff_distance_for_pairs)
            self.cutoff_intersection_for_pairs = float(cutoff_intersection_for_pairs)
            if self.cutoff_distance_for_pairs < 0 or self.cutoff_distance_for_pairs > 1:
                raise ValueError(CUTOFF_RANGE_ERROR_MSG)
            # _Parameters are the clean _parameters to initialize DeepDiff with so we avoid all the above
            # cleaning functionalities when running DeepDiff recursively.
            # However DeepHash has its own set of _parameters that are slightly different than DeepDIff.
            # DeepDiff _parameters are transformed to DeepHash _parameters via _get_deephash_params method.
            self.progress_logger = progress_logger
            self.cache_size = cache_size
            _parameters = self.__dict__.copy()
            _parameters['group_by'] = None  # overwriting since these parameters will be passed on to other passes.

        # Non-Root
        if _shared_parameters:
            self.is_root = False
            self._shared_parameters = _shared_parameters
            self.__dict__.update(_shared_parameters)
            # We are in some pass other than root
            progress_timer = None
        # Root
        else:
            self.is_root = True
            # Caching the DeepDiff results for dynamic programming
            self._distance_cache = LFUCache(cache_size) if cache_size else DummyLFU()
            self._stats = {
                PASSES_COUNT: 0,
                DIFF_COUNT: 0,
                DISTANCE_CACHE_HIT_COUNT: 0,
                PREVIOUS_DIFF_COUNT: 0,
                PREVIOUS_DISTANCE_CACHE_HIT_COUNT: 0,
                MAX_PASS_LIMIT_REACHED: False,
                MAX_DIFF_LIMIT_REACHED: False,
                DISTANCE_CACHE_ENABLED: bool(cache_size),
            }
            self.hashes = dict_() if hashes is None else hashes
            self._numpy_paths = dict_()  # if _numpy_paths is None else _numpy_paths
            self._shared_parameters = {
                'hashes': self.hashes,
                '_stats': self._stats,
                '_distance_cache': self._distance_cache,
                '_numpy_paths': self._numpy_paths,
                _ENABLE_CACHE_EVERY_X_DIFF: self.cache_tuning_sample_size * 10,
            }
            if log_frequency_in_sec:
                # Creating a progress log reporter that runs in a separate thread every log_frequency_in_sec seconds.
                progress_timer = RepeatedTimer(log_frequency_in_sec, _report_progress, self._stats, progress_logger)
            else:
                progress_timer = None

        self._parameters = _parameters
        self.deephash_parameters = self._get_deephash_params()
        self.tree = TreeResult()
        self._iterable_opcodes = {}
        if group_by and self.is_root:
            try:
                original_t1 = t1
                t1 = self._group_iterable_to_dict(t1, group_by, item_name='t1')
            except (KeyError, ValueError):
                pass
            else:
                try:
                    t2 = self._group_iterable_to_dict(t2, group_by, item_name='t2')
                except (KeyError, ValueError):
                    t1 = original_t1

        self.t1 = t1
        self.t2 = t2

        try:
            root = DiffLevel(t1, t2, verbose_level=self.verbose_level)
            # _original_type is only used to pass the original type of the data. Currently only used for numpy arrays.
            # The reason is that we convert the numpy array to python list and then later for distance calculations
            # we convert only the the last dimension of it into numpy arrays.
            self._diff(root, parents_ids=frozenset({id(t1)}), _original_type=_original_type)

            if get_deep_distance and view in {TEXT_VIEW, TREE_VIEW}:
                self.tree['deep_distance'] = self._get_rough_distance()

            self.tree.remove_empty_keys()
            view_results = self._get_view_results(self.view)
            self.update(view_results)
        finally:
            if self.is_root:
                if cache_purge_level:
                    del self._distance_cache
                    del self.hashes
                del self._shared_parameters
                del self._parameters
                for key in (PREVIOUS_DIFF_COUNT, PREVIOUS_DISTANCE_CACHE_HIT_COUNT,
                            DISTANCE_CACHE_ENABLED):
                    del self._stats[key]
                if progress_timer:
                    duration = progress_timer.stop()
                    self._stats['DURATION SEC'] = duration
                    logger.info('stats {}'.format(self.get_stats()))
                if cache_purge_level == 2:
                    self.__dict__.clear()

    def _get_deephash_params(self):
        result = {key: self._parameters[key] for key in DEEPHASH_PARAM_KEYS}
        result['ignore_repetition'] = not self.report_repetition
        result['number_to_string_func'] = self.number_to_string
        return result

    def _report_result(self, report_type, change_level, local_tree=None):
        """
        Add a detected change to the reference-style result dictionary.
        report_type will be added to level.
        (We'll create the text-style report from there later.)
        :param report_type: A well defined string key describing the type of change.
                            Examples: "set_item_added", "values_changed"
        :param change_level: A DiffLevel object describing the objects in question in their
                       before-change and after-change object structure.

        :local_tree: None
        """

        if not self._skip_this(change_level):
            change_level.report_type = report_type
            tree = self.tree if local_tree is None else local_tree
            tree[report_type].add(change_level)

    def custom_report_result(self, report_type, level, extra_info=None):
        """
        Add a detected change to the reference-style result dictionary.
        report_type will be added to level.
        (We'll create the text-style report from there later.)
        :param report_type: A well defined string key describing the type of change.
                            Examples: "set_item_added", "values_changed"
        :param parent: A DiffLevel object describing the objects in question in their
                       before-change and after-change object structure.
        :param extra_info: A dict that describe this result
        :rtype: None
        """

        if not self._skip_this(level):
            level.report_type = report_type
            level.additional[CUSTOM_FIELD] = extra_info
            self.tree[report_type].add(level)

    @staticmethod
    def _dict_from_slots(object):
        def unmangle(attribute):
            if attribute.startswith('__') and attribute != '__weakref__':
                return '_{type}{attribute}'.format(
                    type=type(object).__name__,
                    attribute=attribute
                )
            return attribute

        all_slots = []

        if isinstance(object, type):
            mro = object.__mro__  # pragma: no cover. I have not been able to write a test for this case. But we still check for it.
        else:
            mro = object.__class__.__mro__

        for type_in_mro in mro:
            slots = getattr(type_in_mro, '__slots__', None)
            if slots:
                if isinstance(slots, strings):
                    all_slots.append(slots)
                else:
                    all_slots.extend(slots)

        return {i: getattr(object, unmangle(i)) for i in all_slots}

    def _diff_enum(self, level, parents_ids=frozenset(), local_tree=None):
        t1 = detailed__dict__(level.t1, include_keys=ENUM_INCLUDE_KEYS)
        t2 = detailed__dict__(level.t2, include_keys=ENUM_INCLUDE_KEYS)

        self._diff_dict(
            level,
            parents_ids,
            print_as_attribute=True,
            override=True,
            override_t1=t1,
            override_t2=t2,
            local_tree=local_tree,
        )

    def _diff_obj(self, level, parents_ids=frozenset(), is_namedtuple=False, local_tree=None):
        """Difference of 2 objects"""
        processing_error = False
        try:
            if is_namedtuple:
                t1 = level.t1._asdict()
                t2 = level.t2._asdict()
            elif all('__dict__' in dir(t) for t in level):
                t1 = detailed__dict__(level.t1, ignore_private_variables=self.ignore_private_variables)
                t2 = detailed__dict__(level.t2, ignore_private_variables=self.ignore_private_variables)
            elif all('__slots__' in dir(t) for t in level):
                t1 = self._dict_from_slots(level.t1)
                t2 = self._dict_from_slots(level.t2)
            else:
                t1 = {k: v for k, v in getmembers(level.t1) if not callable(v)}
                t2 = {k: v for k, v in getmembers(level.t2) if not callable(v)}
        except AttributeError:
            processing_error = True
        if processing_error is True:
            self._report_result('unprocessed', level, local_tree=local_tree)
            return

        self._diff_dict(
            level,
            parents_ids,
            print_as_attribute=True,
            override=True,
            override_t1=t1,
            override_t2=t2,
            local_tree=local_tree,
        )

    def _skip_this(self, level):
        """
        Check whether this comparison should be skipped because one of the objects to compare meets exclusion criteria.
        :rtype: bool
        """
        level_path = level.path()
        skip = False
        if self.exclude_paths and level_path in self.exclude_paths:
            skip = True
        if self.include_paths and level_path != 'root':
            if level_path not in self.include_paths:
                skip = True
                for prefix in self.include_paths:
                    if prefix in level_path or level_path in prefix:
                        skip = False
                        break
        elif self.exclude_regex_paths and any(
                [exclude_regex_path.search(level_path) for exclude_regex_path in self.exclude_regex_paths]):
            skip = True
        elif self.exclude_types_tuple and \
                (isinstance(level.t1, self.exclude_types_tuple) or isinstance(level.t2, self.exclude_types_tuple)):
            skip = True
        elif self.exclude_obj_callback and \
                (self.exclude_obj_callback(level.t1, level_path) or self.exclude_obj_callback(level.t2, level_path)):
            skip = True
        elif self.exclude_obj_callback_strict and \
                (self.exclude_obj_callback_strict(level.t1, level_path) and
                 self.exclude_obj_callback_strict(level.t2, level_path)):
            skip = True
        elif self.include_obj_callback and level_path != 'root':
            skip = True
            if (self.include_obj_callback(level.t1, level_path) or self.include_obj_callback(level.t2, level_path)):
                skip = False
        elif self.include_obj_callback_strict and level_path != 'root':
            skip = True
            if (self.include_obj_callback_strict(level.t1, level_path) and
                    self.include_obj_callback_strict(level.t2, level_path)):
                skip = False

        return skip

    def _get_clean_to_keys_mapping(self, keys, level):
        """
        Get a dictionary of cleaned value of keys to the keys themselves.
        This is mainly used to transform the keys when the type changes of keys should be ignored.

        TODO: needs also some key conversion for groups of types other than the built-in strings and numbers.
        """
        result = dict_()
        for key in keys:
            if self.ignore_string_type_changes and isinstance(key, bytes):
                clean_key = key.decode('utf-8')
            elif isinstance(key, numbers):
                type_ = "number" if self.ignore_numeric_type_changes else key.__class__.__name__
                clean_key = self.number_to_string(key, significant_digits=self.significant_digits,
                                                  number_format_notation=self.number_format_notation)
                clean_key = KEY_TO_VAL_STR.format(type_, clean_key)
            else:
                clean_key = key
            if self.ignore_string_case:
                clean_key = clean_key.lower()
            if clean_key in result:
                logger.warning(('{} and {} in {} become the same key when ignore_numeric_type_changes'
                                'or ignore_numeric_type_changes are set to be true.').format(
                                    key, result[clean_key], level.path()))
            else:
                result[clean_key] = key
        return result

    def _diff_dict(
        self,
        level,
        parents_ids=frozenset([]),
        print_as_attribute=False,
        override=False,
        override_t1=None,
        override_t2=None,
        local_tree=None,
    ):
        """Difference of 2 dictionaries"""
        if override:
            # for special stuff like custom objects and named tuples we receive preprocessed t1 and t2
            # but must not spoil the chain (=level) with it
            t1 = override_t1
            t2 = override_t2
        else:
            t1 = level.t1
            t2 = level.t2

        if print_as_attribute:
            item_added_key = "attribute_added"
            item_removed_key = "attribute_removed"
            rel_class = AttributeRelationship
        else:
            item_added_key = "dictionary_item_added"
            item_removed_key = "dictionary_item_removed"
            rel_class = DictRelationship

        if self.ignore_private_variables:
            t1_keys = OrderedSet([key for key in t1 if not(isinstance(key, str) and key.startswith('__'))])
            t2_keys = OrderedSet([key for key in t2 if not(isinstance(key, str) and key.startswith('__'))])
        else:
            t1_keys = OrderedSet(t1.keys())
            t2_keys = OrderedSet(t2.keys())
        if self.ignore_string_type_changes or self.ignore_numeric_type_changes or self.ignore_string_case:
            t1_clean_to_keys = self._get_clean_to_keys_mapping(keys=t1_keys, level=level)
            t2_clean_to_keys = self._get_clean_to_keys_mapping(keys=t2_keys, level=level)
            t1_keys = OrderedSet(t1_clean_to_keys.keys())
            t2_keys = OrderedSet(t2_clean_to_keys.keys())
        else:
            t1_clean_to_keys = t2_clean_to_keys = None

        t_keys_intersect = t2_keys.intersection(t1_keys)

        t_keys_added = t2_keys - t_keys_intersect
        t_keys_removed = t1_keys - t_keys_intersect

        for key in t_keys_added:
            if self._count_diff() is StopIteration:
                return

            key = t2_clean_to_keys[key] if t2_clean_to_keys else key
            change_level = level.branch_deeper(
                notpresent,
                t2[key],
                child_relationship_class=rel_class,
                child_relationship_param=key)
            self._report_result(item_added_key, change_level, local_tree=local_tree)

        for key in t_keys_removed:
            if self._count_diff() is StopIteration:
                return  # pragma: no cover. This is already covered for addition.

            key = t1_clean_to_keys[key] if t1_clean_to_keys else key
            change_level = level.branch_deeper(
                t1[key],
                notpresent,
                child_relationship_class=rel_class,
                child_relationship_param=key)
            self._report_result(item_removed_key, change_level, local_tree=local_tree)

        for key in t_keys_intersect:  # key present in both dicts - need to compare values
            if self._count_diff() is StopIteration:
                return  # pragma: no cover. This is already covered for addition.

            key1 = t1_clean_to_keys[key] if t1_clean_to_keys else key
            key2 = t2_clean_to_keys[key] if t2_clean_to_keys else key
            item_id = id(t1[key1])
            if parents_ids and item_id in parents_ids:
                continue
            parents_ids_added = add_to_frozen_set(parents_ids, item_id)

            # Go one level deeper
            next_level = level.branch_deeper(
                t1[key1],
                t2[key2],
                child_relationship_class=rel_class,
                child_relationship_param=key)
            self._diff(next_level, parents_ids_added, local_tree=local_tree)

    def _diff_set(self, level, local_tree=None):
        """Difference of sets"""
        t1_hashtable = self._create_hashtable(level, 't1')
        t2_hashtable = self._create_hashtable(level, 't2')

        t1_hashes = set(t1_hashtable.keys())
        t2_hashes = set(t2_hashtable.keys())

        hashes_added = t2_hashes - t1_hashes
        hashes_removed = t1_hashes - t2_hashes

        items_added = [t2_hashtable[i].item for i in hashes_added]
        items_removed = [t1_hashtable[i].item for i in hashes_removed]

        for item in items_added:
            if self._count_diff() is StopIteration:
                return  # pragma: no cover. This is already covered for addition.

            change_level = level.branch_deeper(
                notpresent, item, child_relationship_class=SetRelationship)
            self._report_result('set_item_added', change_level, local_tree=local_tree)

        for item in items_removed:
            if self._count_diff() is StopIteration:
                return  # pragma: no cover. This is already covered for addition.

            change_level = level.branch_deeper(
                item, notpresent, child_relationship_class=SetRelationship)
            self._report_result('set_item_removed', change_level, local_tree=local_tree)

    @staticmethod
    def _iterables_subscriptable(t1, t2):
        try:
            if getattr(t1, '__getitem__') and getattr(t2, '__getitem__'):
                return True
            else:  # pragma: no cover
                return False  # should never happen
        except AttributeError:
            return False

    def _diff_iterable(self, level, parents_ids=frozenset(), _original_type=None, local_tree=None):
        """Difference of iterables"""
        if (self.ignore_order_func and self.ignore_order_func(level)) or self.ignore_order:
            self._diff_iterable_with_deephash(level, parents_ids, _original_type=_original_type, local_tree=local_tree)
        else:
            self._diff_iterable_in_order(level, parents_ids, _original_type=_original_type, local_tree=local_tree)

    def _compare_in_order(
        self, level,
        t1_from_index=None, t1_to_index=None,
        t2_from_index=None, t2_to_index=None
    ):
        """
        Default compare if `iterable_compare_func` is not provided.
        This will compare in sequence order.
        """
        if t1_from_index is None:
            return [((i, i), (x, y)) for i, (x, y) in enumerate(
                zip_longest(
                    level.t1, level.t2, fillvalue=ListItemRemovedOrAdded))]
        else:
            t1_chunk = level.t1[t1_from_index:t1_to_index]
            t2_chunk = level.t2[t2_from_index:t2_to_index]
            return [((i + t1_from_index, i + t2_from_index), (x, y)) for i, (x, y) in enumerate(
                zip_longest(
                    t1_chunk, t2_chunk, fillvalue=ListItemRemovedOrAdded))]

    def _get_matching_pairs(
        self, level,
        t1_from_index=None, t1_to_index=None,
        t2_from_index=None, t2_to_index=None
    ):
        """
        Given a level get matching pairs. This returns list of two tuples in the form:
        [
          (t1 index, t2 index), (t1 item, t2 item)
        ]

        This will compare using the passed in `iterable_compare_func` if available.
        Default it to compare in order
        """

        if self.iterable_compare_func is None:
            # Match in order if there is no compare function provided
            return self._compare_in_order(
                level,
                t1_from_index=t1_from_index, t1_to_index=t1_to_index,
                t2_from_index=t2_from_index, t2_to_index=t2_to_index,
            )
        try:
            matches = []
            y_matched = set()
            y_index_matched = set()
            for i, x in enumerate(level.t1):
                x_found = False
                for j, y in enumerate(level.t2):

                    if(j in y_index_matched):
                        # This ensures a one-to-one relationship of matches from t1 to t2.
                        # If y this index in t2 has already been matched to another x
                        # it cannot have another match, so just continue.
                        continue

                    if(self.iterable_compare_func(x, y, level)):
                        deep_hash = DeepHash(y,
                                             hashes=self.hashes,
                                             apply_hash=True,
                                             **self.deephash_parameters,
                                             )
                        y_index_matched.add(j)
                        y_matched.add(deep_hash[y])
                        matches.append(((i, j), (x, y)))
                        x_found = True
                        break

                if(not x_found):
                    matches.append(((i, -1), (x, ListItemRemovedOrAdded)))
            for j, y in enumerate(level.t2):

                deep_hash = DeepHash(y,
                                     hashes=self.hashes,
                                     apply_hash=True,
                                     **self.deephash_parameters,
                                     )
                if(deep_hash[y] not in y_matched):
                    matches.append(((-1, j), (ListItemRemovedOrAdded, y)))
            return matches
        except CannotCompare:
            return self._compare_in_order(
                level,
                t1_from_index=t1_from_index, t1_to_index=t1_to_index,
                t2_from_index=t2_from_index, t2_to_index=t2_to_index
            )

    def _diff_iterable_in_order(self, level, parents_ids=frozenset(), _original_type=None, local_tree=None):
        # We're handling both subscriptable and non-subscriptable iterables. Which one is it?
        subscriptable = self._iterables_subscriptable(level.t1, level.t2)
        if subscriptable:
            child_relationship_class = SubscriptableIterableRelationship
        else:
            child_relationship_class = NonSubscriptableIterableRelationship

        if (
            not self.zip_ordered_iterables
            and isinstance(level.t1, Sequence)
            and isinstance(level.t2, Sequence)
            and self._all_values_basic_hashable(level.t1)
            and self._all_values_basic_hashable(level.t2)
            and self.iterable_compare_func is None
        ):
            local_tree_pass = TreeResult()
            opcodes_with_values = self._diff_ordered_iterable_by_difflib(
                level,
                parents_ids=parents_ids,
                _original_type=_original_type,
                child_relationship_class=child_relationship_class,
                local_tree=local_tree_pass,
            )
            # Sometimes DeepDiff's old iterable diff does a better job than DeepDiff
            if len(local_tree_pass) > 1:
                local_tree_pass2 = TreeResult()
                self._diff_by_forming_pairs_and_comparing_one_by_one(
                    level,
                    parents_ids=parents_ids,
                    _original_type=_original_type,
                    child_relationship_class=child_relationship_class,
                    local_tree=local_tree_pass2,
                )
                if len(local_tree_pass) >= len(local_tree_pass2):
                    local_tree_pass = local_tree_pass2
                else:
                    self._iterable_opcodes[level.path(force=FORCE_DEFAULT)] = opcodes_with_values
            for report_type, levels in local_tree_pass.items():
                if levels:
                    self.tree[report_type] |= levels
        else:
            self._diff_by_forming_pairs_and_comparing_one_by_one(
                level,
                parents_ids=parents_ids,
                _original_type=_original_type,
                child_relationship_class=child_relationship_class,
                local_tree=local_tree,
            )

    def _all_values_basic_hashable(self, iterable):
        """
        Are all items basic hashable types?
        Or there are custom types too?
        """

    # We don't want to exhaust a generator
        if isinstance(iterable, types.GeneratorType):
            return False
        for item in iterable:
            if not isinstance(item, basic_types):
                return False
        return True

    def _diff_by_forming_pairs_and_comparing_one_by_one(
        self, level, local_tree, parents_ids=frozenset(),
        _original_type=None, child_relationship_class=None,
        t1_from_index=None, t1_to_index=None,
        t2_from_index=None, t2_to_index=None,
    ):

        for (i, j), (x, y) in self._get_matching_pairs(
            level, 
            t1_from_index=t1_from_index, t1_to_index=t1_to_index,
            t2_from_index=t2_from_index, t2_to_index=t2_to_index
        ):
            if self._count_diff() is StopIteration:
                return  # pragma: no cover. This is already covered for addition.

            if y is ListItemRemovedOrAdded:  # item removed completely
                change_level = level.branch_deeper(
                    x,
                    notpresent,
                    child_relationship_class=child_relationship_class,
                    child_relationship_param=i)
                self._report_result('iterable_item_removed', change_level, local_tree=local_tree)

            elif x is ListItemRemovedOrAdded:  # new item added
                change_level = level.branch_deeper(
                    notpresent,
                    y,
                    child_relationship_class=child_relationship_class,
                    child_relationship_param=j)
                self._report_result('iterable_item_added', change_level, local_tree=local_tree)

            else:  # check if item value has changed

                # if (i != j):
                #     # Item moved
                #     change_level = level.branch_deeper(
                #         x,
                #         y,
                #         child_relationship_class=child_relationship_class,
                #         child_relationship_param=i,
                #         child_relationship_param2=j
                #     )
                #     self._report_result('iterable_item_moved', change_level)

                # item_id = id(x)
                # if parents_ids and item_id in parents_ids:
                #     continue
                # parents_ids_added = add_to_frozen_set(parents_ids, item_id)

                # # Go one level deeper
                # next_level = level.branch_deeper(
                #     x,
                #     y,
                #     child_relationship_class=child_relationship_class,
                #     child_relationship_param=j)
                # self._diff(next_level, parents_ids_added)

                if (i != j and ((x == y) or self.iterable_compare_func)):
                    # Item moved
                    change_level = level.branch_deeper(
                        x,
                        y,
                        child_relationship_class=child_relationship_class,
                        child_relationship_param=i,
                        child_relationship_param2=j
                    )
                    self._report_result('iterable_item_moved', change_level, local_tree=local_tree)
                    continue

                item_id = id(x)
                if parents_ids and item_id in parents_ids:
                    continue
                parents_ids_added = add_to_frozen_set(parents_ids, item_id)

                # Go one level deeper
                next_level = level.branch_deeper(
                    x,
                    y,
                    child_relationship_class=child_relationship_class,
                    child_relationship_param=i
                    # child_relationship_param=j  # wrong
                )
                self._diff(next_level, parents_ids_added, local_tree=local_tree)

    def _diff_ordered_iterable_by_difflib(
        self, level, local_tree, parents_ids=frozenset(), _original_type=None, child_relationship_class=None,
    ):

        seq = difflib.SequenceMatcher(isjunk=None, a=level.t1, b=level.t2, autojunk=False)

        opcodes = seq.get_opcodes()
        opcodes_with_values = []

        for tag, t1_from_index, t1_to_index, t2_from_index, t2_to_index in opcodes:
            if tag == 'equal':
                opcodes_with_values.append(Opcode(
                    tag, t1_from_index, t1_to_index, t2_from_index, t2_to_index,
                ))
                continue
            # print('{:7}   t1[{}:{}] --> t2[{}:{}] {!r:>8} --> {!r}'.format(
            #     tag, t1_from_index, t1_to_index, t2_from_index, t2_to_index, level.t1[t1_from_index:t1_to_index], level.t2[t2_from_index:t2_to_index]))

            opcodes_with_values.append(Opcode(
                tag, t1_from_index, t1_to_index, t2_from_index, t2_to_index,
                old_values = level.t1[t1_from_index: t1_to_index],
                new_values = level.t2[t2_from_index: t2_to_index],
            ))

            if tag == 'replace':
                self._diff_by_forming_pairs_and_comparing_one_by_one(
                    level, local_tree=local_tree, parents_ids=parents_ids,
                    _original_type=_original_type, child_relationship_class=child_relationship_class,
                    t1_from_index=t1_from_index, t1_to_index=t1_to_index,
                    t2_from_index=t2_from_index, t2_to_index=t2_to_index,
                )
            elif tag == 'delete':
                for index, x in enumerate(level.t1[t1_from_index:t1_to_index]):
                    change_level = level.branch_deeper(
                        x,
                        notpresent,
                        child_relationship_class=child_relationship_class,
                        child_relationship_param=index + t1_from_index)
                    self._report_result('iterable_item_removed', change_level, local_tree=local_tree)
            elif tag == 'insert':
                for index, y in enumerate(level.t2[t2_from_index:t2_to_index]):
                    change_level = level.branch_deeper(
                        notpresent,
                        y,
                        child_relationship_class=child_relationship_class,
                        child_relationship_param=index + t2_from_index)
                    self._report_result('iterable_item_added', change_level, local_tree=local_tree)
        return opcodes_with_values


    def _diff_str(self, level, local_tree=None):
        """Compare strings"""
        if self.ignore_string_case:
            level.t1 = level.t1.lower()
            level.t2 = level.t2.lower()

        if type(level.t1) == type(level.t2) and level.t1 == level.t2:  # NOQA
            return

        # do we add a diff for convenience?
        do_diff = True
        t1_str = level.t1
        t2_str = level.t2

        if isinstance(level.t1, bytes_type):
            try:
                t1_str = level.t1.decode('ascii')
            except UnicodeDecodeError:
                do_diff = False

        if isinstance(level.t2, bytes_type):
            try:
                t2_str = level.t2.decode('ascii')
            except UnicodeDecodeError:
                do_diff = False

        if isinstance(level.t1, Enum):
            t1_str = level.t1.value

        if isinstance(level.t2, Enum):
            t2_str = level.t2.value

        if t1_str == t2_str:
            return

        if do_diff:
            if '\n' in t1_str or isinstance(t2_str, str) and '\n' in t2_str:
                diff = difflib.unified_diff(
                    t1_str.splitlines(), t2_str.splitlines(), lineterm='')
                diff = list(diff)
                if diff:
                    level.additional['diff'] = '\n'.join(diff)

        self._report_result('values_changed', level, local_tree=local_tree)

    def _diff_tuple(self, level, parents_ids, local_tree=None):
        # Checking to see if it has _fields. Which probably means it is a named
        # tuple.
        try:
            level.t1._asdict
        # It must be a normal tuple
        except AttributeError:
            self._diff_iterable(level, parents_ids, local_tree=local_tree)
        # We assume it is a namedtuple then
        else:
            self._diff_obj(level, parents_ids, is_namedtuple=True, local_tree=local_tree)

    def _add_hash(self, hashes, item_hash, item, i):
        if item_hash in hashes:
            hashes[item_hash].indexes.append(i)
        else:
            hashes[item_hash] = IndexedHash(indexes=[i], item=item)

    def _create_hashtable(self, level, t):
        """Create hashtable of {item_hash: (indexes, item)}"""
        obj = getattr(level, t)

        local_hashes = dict_()
        for (i, item) in enumerate(obj):
            try:
                parent = "{}[{}]".format(level.path(), i)
                # Note: in the DeepDiff we only calculate the hash of items when we have to.
                # So self.hashes does not include hashes of all objects in t1 and t2.
                # It only includes the ones needed when comparing iterables.
                # The self.hashes dictionary gets shared between different runs of DeepHash
                # So that any object that is already calculated to have a hash is not re-calculated.
                deep_hash = DeepHash(item,
                                     hashes=self.hashes,
                                     parent=parent,
                                     apply_hash=True,
                                     **self.deephash_parameters,
                                     )
            except UnicodeDecodeError as err:
                err.reason = f"Can not produce a hash for {level.path()}: {err.reason}"
                raise
            except Exception as e:  # pragma: no cover
                logger.error("Can not produce a hash for %s."
                             "Not counting this object.\n %s" %
                             (level.path(), e))
            else:
                try:
                    item_hash = deep_hash[item]
                except KeyError:
                    pass
                else:
                    if item_hash is unprocessed:  # pragma: no cover
                        logger.warning("Item %s was not processed while hashing "
                                       "thus not counting this object." %
                                       level.path())
                    else:
                        self._add_hash(hashes=local_hashes, item_hash=item_hash, item=item, i=i)

        # Also we hash the iterables themselves too so that we can later create cache keys from those hashes.
        try:
            DeepHash(
                obj,
                hashes=self.hashes,
                parent=level.path(),
                apply_hash=True,
                **self.deephash_parameters,
            )
        except Exception as e:  # pragma: no cover
            logger.error("Can not produce a hash for iterable %s. %s" %
                         (level.path(), e))
        return local_hashes

    @staticmethod
    def _get_distance_cache_key(added_hash, removed_hash):
        key1, key2 = (added_hash, removed_hash) if added_hash > removed_hash else (removed_hash, added_hash)
        if isinstance(key1, int):
            # If the hash function produces integers we convert them to hex values.
            # This was used when the default hash function was Murmur3 128bit which produces integers.
            key1 = hex(key1).encode('utf-8')
            key2 = hex(key2).encode('utf-8')
        elif isinstance(key1, str):
            key1 = key1.encode('utf-8')
            key2 = key2.encode('utf-8')
        return key1 + b'--' + key2 + b'dc'

    def _get_rough_distance_of_hashed_objs(
            self, added_hash, removed_hash, added_hash_obj, removed_hash_obj, _original_type=None):
        # We need the rough distance between the 2 objects to see if they qualify to be pairs or not
        _distance = cache_key = None
        if self._stats[DISTANCE_CACHE_ENABLED]:
            cache_key = self._get_distance_cache_key(added_hash, removed_hash)
            if cache_key in self._distance_cache:
                self._stats[DISTANCE_CACHE_HIT_COUNT] += 1
                _distance = self._distance_cache.get(cache_key)
        if _distance is None:
            # We can only cache the rough distance and not the actual diff result for reuse.
            # The reason is that we have modified the parameters explicitly so they are different and can't
            # be used for diff reporting
            diff = DeepDiff(
                removed_hash_obj.item, added_hash_obj.item,
                _parameters=self._parameters,
                _shared_parameters=self._shared_parameters,
                view=DELTA_VIEW,
                _original_type=_original_type,
                iterable_compare_func=self.iterable_compare_func,
            )
            _distance = diff._get_rough_distance()
            if cache_key and self._stats[DISTANCE_CACHE_ENABLED]:
                self._distance_cache.set(cache_key, value=_distance)
        return _distance

    def _get_most_in_common_pairs_in_iterables(
            self, hashes_added, hashes_removed, t1_hashtable, t2_hashtable, parents_ids, _original_type):
        """
        Get the closest pairs between items that are removed and items that are added.

        returns a dictionary of hashes that are closest to each other.
        The dictionary is going to be symmetrical so any key will be a value too and otherwise.

        Note that due to the current reporting structure in DeepDiff, we don't compare an item that
        was added to an item that is in both t1 and t2.

        For example

        [{1, 2}, {4, 5, 6}]
        [{1, 2}, {1, 2, 3}]

        is only compared between {4, 5, 6} and {1, 2, 3} even though technically {1, 2, 3} is
        just one item different than {1, 2}

        Perhaps in future we can have a report key that is item duplicated and modified instead of just added.
        """
        cache_key = None
        if self._stats[DISTANCE_CACHE_ENABLED]:
            cache_key = combine_hashes_lists(items=[hashes_added, hashes_removed], prefix='pairs_cache')
            if cache_key in self._distance_cache:
                return self._distance_cache.get(cache_key).copy()

        # A dictionary of hashes to distances and each distance to an ordered set of hashes.
        # It tells us about the distance of each object from other objects.
        # And the objects with the same distances are grouped together in an ordered set.
        # It also includes a "max" key that is just the value of the biggest current distance in the
        # most_in_common_pairs dictionary.
        def defaultdict_orderedset():
            return defaultdict(OrderedSetPlus)
        most_in_common_pairs = defaultdict(defaultdict_orderedset)
        pairs = dict_()

        pre_calced_distances = None

        if hashes_added and hashes_removed and np and len(hashes_added) > 1 and len(hashes_removed) > 1:
            # pre-calculates distances ONLY for 1D arrays whether an _original_type
            # was explicitly passed or a homogeneous array is detected.
            # Numpy is needed for this optimization.
            pre_calced_distances = self._precalculate_numpy_arrays_distance(
                hashes_added, hashes_removed, t1_hashtable, t2_hashtable, _original_type)

        if hashes_added and hashes_removed and self.iterable_compare_func and len(hashes_added) > 1 and len(hashes_removed) > 1:
            pre_calced_distances = self._precalculate_distance_by_custom_compare_func(
                hashes_added, hashes_removed, t1_hashtable, t2_hashtable, _original_type)

        for added_hash in hashes_added:
            for removed_hash in hashes_removed:
                added_hash_obj = t2_hashtable[added_hash]
                removed_hash_obj = t1_hashtable[removed_hash]

                # Loop is detected
                if id(removed_hash_obj.item) in parents_ids:
                    continue

                _distance = None
                if pre_calced_distances:
                    _distance = pre_calced_distances.get("{}--{}".format(added_hash, removed_hash))
                if _distance is None:
                    _distance = self._get_rough_distance_of_hashed_objs(
                        added_hash, removed_hash, added_hash_obj, removed_hash_obj, _original_type)
                # Left for future debugging
                # print(f'{Fore.RED}distance of {added_hash_obj.item} and {removed_hash_obj.item}: {_distance}{Style.RESET_ALL}')
                # Discard potential pairs that are too far.
                if _distance >= self.cutoff_distance_for_pairs:
                    continue
                pairs_of_item = most_in_common_pairs[added_hash]
                pairs_of_item[_distance].add(removed_hash)
        used_to_hashes = set()

        distances_to_from_hashes = defaultdict(OrderedSetPlus)
        for from_hash, distances_to_to_hashes in most_in_common_pairs.items():
            # del distances_to_to_hashes['max']
            for dist in distances_to_to_hashes:
                distances_to_from_hashes[dist].add(from_hash)

        for dist in sorted(distances_to_from_hashes.keys()):
            from_hashes = distances_to_from_hashes[dist]
            while from_hashes:
                from_hash = from_hashes.lpop()
                if from_hash not in used_to_hashes:
                    to_hashes = most_in_common_pairs[from_hash][dist]
                    while to_hashes:
                        to_hash = to_hashes.lpop()
                        if to_hash not in used_to_hashes:
                            used_to_hashes.add(from_hash)
                            used_to_hashes.add(to_hash)
                            # Left for future debugging:
                            # print(f'{bcolors.FAIL}Adding {t2_hashtable[from_hash].item} as a pairs of {t1_hashtable[to_hash].item} with distance of {dist}{bcolors.ENDC}')
                            pairs[from_hash] = to_hash

        inverse_pairs = {v: k for k, v in pairs.items()}
        pairs.update(inverse_pairs)
        if cache_key and self._stats[DISTANCE_CACHE_ENABLED]:
            self._distance_cache.set(cache_key, value=pairs)
        return pairs.copy()

    def _diff_iterable_with_deephash(self, level, parents_ids, _original_type=None, local_tree=None):
        """Diff of hashable or unhashable iterables. Only used when ignoring the order."""

        full_t1_hashtable = self._create_hashtable(level, 't1')
        full_t2_hashtable = self._create_hashtable(level, 't2')
        t1_hashes = OrderedSetPlus(full_t1_hashtable.keys())
        t2_hashes = OrderedSetPlus(full_t2_hashtable.keys())
        hashes_added = t2_hashes - t1_hashes
        hashes_removed = t1_hashes - t2_hashes

        # Deciding whether to calculate pairs or not.
        if (len(hashes_added) + len(hashes_removed)) / (len(full_t1_hashtable) + len(full_t2_hashtable) + 1) > self.cutoff_intersection_for_pairs:
            get_pairs = False
        else:
            get_pairs = True

        # reduce the size of hashtables
        if self.report_repetition:
            t1_hashtable = full_t1_hashtable
            t2_hashtable = full_t2_hashtable
        else:
            t1_hashtable = {k: v for k, v in full_t1_hashtable.items() if k in hashes_removed}
            t2_hashtable = {k: v for k, v in full_t2_hashtable.items() if k in hashes_added}

        if self._stats[PASSES_COUNT] < self.max_passes and get_pairs:
            self._stats[PASSES_COUNT] += 1
            pairs = self._get_most_in_common_pairs_in_iterables(
                hashes_added, hashes_removed, t1_hashtable, t2_hashtable, parents_ids, _original_type)
        elif get_pairs:
            if not self._stats[MAX_PASS_LIMIT_REACHED]:
                self._stats[MAX_PASS_LIMIT_REACHED] = True
                logger.warning(MAX_PASSES_REACHED_MSG.format(self.max_passes))
            pairs = dict_()
        else:
            pairs = dict_()

        def get_other_pair(hash_value, in_t1=True):
            """
            Gets the other paired indexed hash item to the hash_value in the pairs dictionary
            in_t1: are we looking for the other pair in t1 or t2?
            """
            if in_t1:
                hashtable = t1_hashtable
                the_other_hashes = hashes_removed
            else:
                hashtable = t2_hashtable
                the_other_hashes = hashes_added
            other = pairs.pop(hash_value, notpresent)
            if other is notpresent:
                other = notpresent_indexed
            else:
                # The pairs are symmetrical.
                # removing the other direction of pair
                # so it does not get used.
                del pairs[other]
                the_other_hashes.remove(other)
                other = hashtable[other]
            return other

        if self.report_repetition:
            for hash_value in hashes_added:
                if self._count_diff() is StopIteration:
                    return  # pragma: no cover. This is already covered for addition (when report_repetition=False).
                other = get_other_pair(hash_value)
                item_id = id(other.item)
                indexes = t2_hashtable[hash_value].indexes if other.item is notpresent else other.indexes
                for i in indexes:
                    change_level = level.branch_deeper(
                        other.item,
                        t2_hashtable[hash_value].item,
                        child_relationship_class=SubscriptableIterableRelationship,
                        child_relationship_param=i
                    )
                    if other.item is notpresent:
                        self._report_result('iterable_item_added', change_level, local_tree=local_tree)
                    else:
                        parents_ids_added = add_to_frozen_set(parents_ids, item_id)
                        self._diff(change_level, parents_ids_added, local_tree=local_tree)
            for hash_value in hashes_removed:
                if self._count_diff() is StopIteration:
                    return  # pragma: no cover. This is already covered for addition.
                other = get_other_pair(hash_value, in_t1=False)
                item_id = id(other.item)
                for i in t1_hashtable[hash_value].indexes:
                    change_level = level.branch_deeper(
                        t1_hashtable[hash_value].item,
                        other.item,
                        child_relationship_class=SubscriptableIterableRelationship,
                        child_relationship_param=i)
                    if other.item is notpresent:
                        self._report_result('iterable_item_removed', change_level, local_tree=local_tree)
                    else:
                        # I was not able to make a test case for the following 2 lines since the cases end up
                        # getting resolved above in the hashes_added calcs. However I am leaving these 2 lines
                        # in case things change in future.
                        parents_ids_added = add_to_frozen_set(parents_ids, item_id)  # pragma: no cover.
                        self._diff(change_level, parents_ids_added, local_tree=local_tree)  # pragma: no cover.

            items_intersect = t2_hashes.intersection(t1_hashes)

            for hash_value in items_intersect:
                t1_indexes = t1_hashtable[hash_value].indexes
                t2_indexes = t2_hashtable[hash_value].indexes
                t1_indexes_len = len(t1_indexes)
                t2_indexes_len = len(t2_indexes)
                if t1_indexes_len != t2_indexes_len:  # this is a repetition change!
                    # create "change" entry, keep current level untouched to handle further changes
                    repetition_change_level = level.branch_deeper(
                        t1_hashtable[hash_value].item,
                        t2_hashtable[hash_value].item,  # nb: those are equal!
                        child_relationship_class=SubscriptableIterableRelationship,
                        child_relationship_param=t1_hashtable[hash_value]
                        .indexes[0])
                    repetition_change_level.additional['repetition'] = RemapDict(
                        old_repeat=t1_indexes_len,
                        new_repeat=t2_indexes_len,
                        old_indexes=t1_indexes,
                        new_indexes=t2_indexes)
                    self._report_result('repetition_change',
                                        repetition_change_level, local_tree=local_tree)

        else:
            for hash_value in hashes_added:
                if self._count_diff() is StopIteration:
                    return
                other = get_other_pair(hash_value)
                item_id = id(other.item)
                index = t2_hashtable[hash_value].indexes[0] if other.item is notpresent else other.indexes[0]
                change_level = level.branch_deeper(
                    other.item,
                    t2_hashtable[hash_value].item,
                    child_relationship_class=SubscriptableIterableRelationship,
                    child_relationship_param=index)
                if other.item is notpresent:
                    self._report_result('iterable_item_added', change_level, local_tree=local_tree)
                else:
                    parents_ids_added = add_to_frozen_set(parents_ids, item_id)
                    self._diff(change_level, parents_ids_added, local_tree=local_tree)

            for hash_value in hashes_removed:
                if self._count_diff() is StopIteration:
                    return  # pragma: no cover. This is already covered for addition.
                other = get_other_pair(hash_value, in_t1=False)
                item_id = id(other.item)
                change_level = level.branch_deeper(
                    t1_hashtable[hash_value].item,
                    other.item,
                    child_relationship_class=SubscriptableIterableRelationship,
                    child_relationship_param=t1_hashtable[hash_value].indexes[
                        0])
                if other.item is notpresent:
                    self._report_result('iterable_item_removed', change_level, local_tree=local_tree)
                else:
                    # Just like the case when report_repetition = True, these lines never run currently.
                    # However they will stay here in case things change in future.
                    parents_ids_added = add_to_frozen_set(parents_ids, item_id)  # pragma: no cover.
                    self._diff(change_level, parents_ids_added, local_tree=local_tree)  # pragma: no cover.

    def _diff_booleans(self, level, local_tree=None):
        if level.t1 != level.t2:
            self._report_result('values_changed', level, local_tree=local_tree)

    def _diff_numbers(self, level, local_tree=None, report_type_change=True):
        """Diff Numbers"""
        if report_type_change:
            t1_type = "number" if self.ignore_numeric_type_changes else level.t1.__class__.__name__
            t2_type = "number" if self.ignore_numeric_type_changes else level.t2.__class__.__name__
        else:
            t1_type = t2_type = ''

        if self.math_epsilon is not None:
            if not is_close(level.t1, level.t2, abs_tol=self.math_epsilon):
                self._report_result('values_changed', level, local_tree=local_tree)
        elif self.significant_digits is None:
            if level.t1 != level.t2:
                self._report_result('values_changed', level, local_tree=local_tree)
        else:
            # Bernhard10: I use string formatting for comparison, to be consistent with usecases where
            # data is read from files that were previously written from python and
            # to be consistent with on-screen representation of numbers.
            # Other options would be abs(t1-t2)<10**-self.significant_digits
            # or math.is_close (python3.5+)
            # Note that abs(3.25-3.251) = 0.0009999999999998899 < 0.001
            # Note also that "{:.3f}".format(1.1135) = 1.113, but "{:.3f}".format(1.11351) = 1.114
            # For Decimals, format seems to round 2.5 to 2 and 3.5 to 4 (to closest even number)
            t1_s = self.number_to_string(level.t1,
                                         significant_digits=self.significant_digits,
                                         number_format_notation=self.number_format_notation)
            t2_s = self.number_to_string(level.t2,
                                         significant_digits=self.significant_digits,
                                         number_format_notation=self.number_format_notation)

            t1_s = KEY_TO_VAL_STR.format(t1_type, t1_s)
            t2_s = KEY_TO_VAL_STR.format(t2_type, t2_s)
            if t1_s != t2_s:
                self._report_result('values_changed', level, local_tree=local_tree)

    def _diff_datetimes(self, level, local_tree=None):
        """Diff DateTimes"""
        if self.truncate_datetime:
            level.t1 = datetime_normalize(self.truncate_datetime, level.t1)
            level.t2 = datetime_normalize(self.truncate_datetime, level.t2)

        if level.t1 != level.t2:
            self._report_result('values_changed', level, local_tree=local_tree)

    def _diff_uuids(self, level, local_tree=None):
        """Diff UUIDs"""
        if level.t1.int != level.t2.int:
            self._report_result('values_changed', level, local_tree=local_tree)

    def _diff_numpy_array(self, level, parents_ids=frozenset(), local_tree=None):
        """Diff numpy arrays"""
        if level.path() not in self._numpy_paths:
            self._numpy_paths[level.path()] = get_type(level.t2).__name__
        if np is None:
            # This line should never be run. If it is ever called means the type check detected a numpy array
            # which means numpy module needs to be available. So np can't be None.
            raise ImportError(CANT_FIND_NUMPY_MSG)  # pragma: no cover

        if (self.ignore_order_func and not self.ignore_order_func(level)) or not self.ignore_order:
            # fast checks
            if self.significant_digits is None:
                if np.array_equal(level.t1, level.t2, equal_nan=self.ignore_nan_inequality):
                    return  # all good
            else:
                try:
                    np.testing.assert_almost_equal(level.t1, level.t2, decimal=self.significant_digits)
                except TypeError:
                    np.array_equal(level.t1, level.t2, equal_nan=self.ignore_nan_inequality)
                except AssertionError:
                    pass    # do detailed checking below
                else:
                    return  # all good

        # compare array meta-data
        _original_type = level.t1.dtype
        if level.t1.shape != level.t2.shape:
            # arrays are converted to python lists so that certain features of DeepDiff can apply on them easier.
            # They will be converted back to Numpy at their final dimension.
            level.t1 = level.t1.tolist()
            level.t2 = level.t2.tolist()
            self._diff_iterable(level, parents_ids, _original_type=_original_type, local_tree=local_tree)
        else:
            # metadata same -- the difference is in the content
            shape = level.t1.shape
            dimensions = len(shape)
            if dimensions == 1:
                self._diff_iterable(level, parents_ids, _original_type=_original_type, local_tree=local_tree)
            elif (self.ignore_order_func and self.ignore_order_func(level)) or self.ignore_order:
                # arrays are converted to python lists so that certain features of DeepDiff can apply on them easier.
                # They will be converted back to Numpy at their final dimension.
                level.t1 = level.t1.tolist()
                level.t2 = level.t2.tolist()
                self._diff_iterable_with_deephash(level, parents_ids, _original_type=_original_type, local_tree=local_tree)
            else:
                for (t1_path, t1_row), (t2_path, t2_row) in zip(
                        get_numpy_ndarray_rows(level.t1, shape),
                        get_numpy_ndarray_rows(level.t2, shape)):

                    new_level = level.branch_deeper(
                        t1_row,
                        t2_row,
                        child_relationship_class=NumpyArrayRelationship,
                        child_relationship_param=t1_path)

                    self._diff_iterable_in_order(new_level, parents_ids, _original_type=_original_type, local_tree=local_tree)

    def _diff_types(self, level, local_tree=None):
        """Diff types"""
        level.report_type = 'type_changes'
        self._report_result('type_changes', level, local_tree=local_tree)

    def _count_diff(self):
        if (self.max_diffs is not None and self._stats[DIFF_COUNT] > self.max_diffs):
            if not self._stats[MAX_DIFF_LIMIT_REACHED]:
                self._stats[MAX_DIFF_LIMIT_REACHED] = True
                logger.warning(MAX_DIFFS_REACHED_MSG.format(self.max_diffs))
            return StopIteration
        self._stats[DIFF_COUNT] += 1
        if self.cache_size and self.cache_tuning_sample_size:
            self._auto_tune_cache()

    def _auto_tune_cache(self):
        take_sample = (self._stats[DIFF_COUNT] % self.cache_tuning_sample_size == 0)
        if self.cache_tuning_sample_size:
            if self._stats[DISTANCE_CACHE_ENABLED]:
                if take_sample:
                    self._auto_off_cache()
            # Turn on the cache once in a while
            elif self._stats[DIFF_COUNT] % self._shared_parameters[_ENABLE_CACHE_EVERY_X_DIFF] == 0:
                self.progress_logger('Re-enabling the distance and level caches.')
                # decreasing the sampling frequency
                self._shared_parameters[_ENABLE_CACHE_EVERY_X_DIFF] *= 10
                self._stats[DISTANCE_CACHE_ENABLED] = True
        if take_sample:
            for key in (PREVIOUS_DIFF_COUNT, PREVIOUS_DISTANCE_CACHE_HIT_COUNT):
                self._stats[key] = self._stats[key[9:]]

    def _auto_off_cache(self):
        """
        Auto adjust the cache based on the usage
        """
        if self._stats[DISTANCE_CACHE_ENABLED]:
            angle = (self._stats[DISTANCE_CACHE_HIT_COUNT] - self._stats['PREVIOUS {}'.format(DISTANCE_CACHE_HIT_COUNT)]) / (self._stats[DIFF_COUNT] - self._stats[PREVIOUS_DIFF_COUNT])
            if angle < self.CACHE_AUTO_ADJUST_THRESHOLD:
                self._stats[DISTANCE_CACHE_ENABLED] = False
                self.progress_logger('Due to minimal cache hits, {} is disabled.'.format('distance cache'))

    def _use_custom_operator(self, level):
        """
        For each level we check all custom operators.
        If any one of them was a match for the level, we run the diff of the operator.
        If the operator returned True, the operator must have decided these objects should not
        be compared anymore. It might have already reported their results.
        In that case the report will appear in the final results of this diff.
        Otherwise basically the 2 objects in the level are being omitted from the results.
        """

        for operator in self.custom_operators:
            if operator.match(level):
                prevent_default = operator.give_up_diffing(level=level, diff_instance=self)
                if prevent_default:
                    return True

        return False

    def _diff(self, level, parents_ids=frozenset(), _original_type=None, local_tree=None):
        """
        The main diff method

        **parameters**

        level: the tree level or tree node
        parents_ids: the ids of all the parent objects in the tree from the current node.
        _original_type: If the objects had an original type that was different than what currently exists in the level.t1 and t2
        """
        if self._count_diff() is StopIteration:
            return

        if self._use_custom_operator(level):
            return

        if level.t1 is level.t2:
            return

        if self._skip_this(level):
            return

        report_type_change = True
        if get_type(level.t1) != get_type(level.t2):
            for type_group in self.ignore_type_in_groups:
                if self.type_check_func(level.t1, type_group) and self.type_check_func(level.t2, type_group):
                    report_type_change = False
                    break
            if report_type_change:
                self._diff_types(level, local_tree=local_tree)
                return
            # This is an edge case where t1=None or t2=None and None is in the ignore type group.
            if level.t1 is None or level.t2 is None:
                self._report_result('values_changed', level, local_tree=local_tree)
                return

        if self.ignore_nan_inequality and isinstance(level.t1, (float, np_floating)) and str(level.t1) == str(level.t2) == 'nan':
            return

        if isinstance(level.t1, booleans):
            self._diff_booleans(level, local_tree=local_tree)

        elif isinstance(level.t1, strings):
            self._diff_str(level, local_tree=local_tree)

        elif isinstance(level.t1, datetimes):
            self._diff_datetimes(level, local_tree=local_tree)

        elif isinstance(level.t1, uuids):
            self._diff_uuids(level, local_tree=local_tree)

        elif isinstance(level.t1, numbers):
            self._diff_numbers(level, local_tree=local_tree, report_type_change=report_type_change)

        elif isinstance(level.t1, Mapping):
            self._diff_dict(level, parents_ids, local_tree=local_tree)

        elif isinstance(level.t1, tuple):
            self._diff_tuple(level, parents_ids, local_tree=local_tree)

        elif isinstance(level.t1, (set, frozenset, OrderedSet)):
            self._diff_set(level, local_tree=local_tree)

        elif isinstance(level.t1, np_ndarray):
            self._diff_numpy_array(level, parents_ids, local_tree=local_tree)

        elif isinstance(level.t1, PydanticBaseModel):
            self._diff_obj(level, parents_ids, local_tree=local_tree)

        elif isinstance(level.t1, Iterable):
            self._diff_iterable(level, parents_ids, _original_type=_original_type, local_tree=local_tree)

        elif isinstance(level.t1, Enum):
            self._diff_enum(level, parents_ids, local_tree=local_tree)

        else:
            self._diff_obj(level, parents_ids)

    def _get_view_results(self, view):
        """
        Get the results based on the view
        """
        result = self.tree
        if not self.report_repetition:  # and self.is_root:
            result.mutual_add_removes_to_become_value_changes()
        if view == TREE_VIEW:
            pass
        elif view == TEXT_VIEW:
            result = TextResult(tree_results=self.tree, verbose_level=self.verbose_level)
            result.remove_empty_keys()
        elif view == DELTA_VIEW:
            result = self._to_delta_dict(report_repetition_required=False)
        else:
            raise ValueError(INVALID_VIEW_MSG.format(view))
        return result

    @staticmethod
    def _get_key_for_group_by(row, group_by, item_name):
        try:
            return row.pop(group_by)
        except KeyError:
            logger.error("Unable to group {} by {}. The key is missing in {}".format(item_name, group_by, row))
            raise

    def _group_iterable_to_dict(self, item, group_by, item_name):
        """
        Convert a list of dictionaries into a dictionary of dictionaries
        where the key is the value of the group_by key in each dictionary.
        """
        group_by_level2 = None
        if isinstance(group_by, (list, tuple)):
            group_by_level1 = group_by[0]
            if len(group_by) > 1:
                group_by_level2 = group_by[1]
        else:
            group_by_level1 = group_by
        if isinstance(item, Iterable) and not isinstance(item, Mapping):
            result = {}
            item_copy = deepcopy(item)
            for row in item_copy:
                if isinstance(row, Mapping):
                    key1 = self._get_key_for_group_by(row, group_by_level1, item_name)
                    if group_by_level2:
                        key2 = self._get_key_for_group_by(row, group_by_level2, item_name)
                        if key1 not in result:
                            result[key1] = {}
                        if self.group_by_sort_key:
                            if key2 not in result[key1]:
                                result[key1][key2] = []
                            result_key1_key2 = result[key1][key2]
                            if row not in result_key1_key2:
                                result_key1_key2.append(row)
                        else:
                            result[key1][key2] = row
                    else:
                        if self.group_by_sort_key:
                            if key1 not in result:
                                result[key1] = []
                            if row not in result[key1]:
                                result[key1].append(row)
                        else:
                            result[key1] = row
                else:
                    msg = "Unable to group {} by {} since the item {} is not a dictionary.".format(item_name, group_by_level1, row)
                    logger.error(msg)
                    raise ValueError(msg)
            if self.group_by_sort_key:
                if group_by_level2:
                    for key1, row1 in result.items():
                        for key2, row in row1.items():
                            row.sort(key=self.group_by_sort_key)
                else:
                    for key, row in result.items():
                        row.sort(key=self.group_by_sort_key)
            return result
        msg = "Unable to group {} by {}".format(item_name, group_by)
        logger.error(msg)
        raise ValueError(msg)

    def get_stats(self):
        """
        Get some stats on internals of the DeepDiff run.
        """
        return self._stats

    @property
    def affected_paths(self):
        """
        Get the list of paths that were affected.
        Whether a value was changed or they were added or removed.

        Example
            >>> t1 = {1: 1, 2: 2, 3: [3], 4: 4}
            >>> t2 = {1: 1, 2: 4, 3: [3, 4], 5: 5, 6: 6}
            >>> ddiff = DeepDiff(t1, t2)
            >>> ddiff
            >>> pprint(ddiff, indent=4)
            {   'dictionary_item_added': [root[5], root[6]],
                'dictionary_item_removed': [root[4]],
                'iterable_item_added': {'root[3][1]': 4},
                'values_changed': {'root[2]': {'new_value': 4, 'old_value': 2}}}
            >>> ddiff.affected_paths
            OrderedSet(['root[3][1]', 'root[4]', 'root[5]', 'root[6]', 'root[2]'])
            >>> ddiff.affected_root_keys
            OrderedSet([3, 4, 5, 6, 2])

        """
        result = OrderedSet()
        for key in REPORT_KEYS:
            value = self.get(key)
            if value:
                if isinstance(value, PrettyOrderedSet):
                    result |= value
                else:
                    result |= OrderedSet(value.keys())
        return result

    @property
    def affected_root_keys(self):
        """
        Get the list of root keys that were affected.
        Whether a value was changed or they were added or removed.

        Example
            >>> t1 = {1: 1, 2: 2, 3: [3], 4: 4}
            >>> t2 = {1: 1, 2: 4, 3: [3, 4], 5: 5, 6: 6}
            >>> ddiff = DeepDiff(t1, t2)
            >>> ddiff
            >>> pprint(ddiff, indent=4)
            {   'dictionary_item_added': [root[5], root[6]],
                'dictionary_item_removed': [root[4]],
                'iterable_item_added': {'root[3][1]': 4},
                'values_changed': {'root[2]': {'new_value': 4, 'old_value': 2}}}
            >>> ddiff.affected_paths
            OrderedSet(['root[3][1]', 'root[4]', 'root[5]', 'root[6]', 'root[2]'])
            >>> ddiff.affected_root_keys
            OrderedSet([3, 4, 5, 6, 2])
        """
        result = OrderedSet()
        for key in REPORT_KEYS:
            value = self.tree.get(key)
            if value:
                if isinstance(value, PrettyOrderedSet):
                    result |= OrderedSet([i.get_root_key() for i in value])
                else:
                    result |= OrderedSet([i.get_root_key() for i in value.keys()])
        return result


if __name__ == "__main__":  # pragma: no cover
    import doctest
    doctest.testmod()
