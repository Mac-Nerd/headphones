from collections.abc import Iterable, Mapping
from uuid import uuid4

import six

from apscheduler.triggers.base import BaseTrigger
from apscheduler.util import ref_to_obj, obj_to_ref, datetime_repr, repr_escape, get_callable_name, check_callable_args, \
    convert_to_datetime


class Job(object):
    """
    Contains the options given when scheduling callables and its current schedule and other state.
    This class should never be instantiated by the user.

    :var str id: the unique identifier of this job
    :var str name: the description of this job
    :var func: the callable to execute
    :var tuple|list args: positional arguments to the callable
    :var dict kwargs: keyword arguments to the callable
    :var bool coalesce: whether to only run the job once when several run times are due
    :var trigger: the trigger object that controls the schedule of this job
    :var str executor: the name of the executor that will run this job
    :var int misfire_grace_time: the time (in seconds) how much this job's execution is allowed to be late
    :var int max_instances: the maximum number of concurrently executing instances allowed for this job
    :var datetime.datetime next_run_time: the next scheduled run time of this job
    """

    __slots__ = ('_scheduler', '_jobstore_alias', 'id', 'trigger', 'executor', 'func', 'func_ref', 'args', 'kwargs',
                 'name', 'misfire_grace_time', 'coalesce', 'max_instances', 'next_run_time')

    def __init__(self, scheduler, id=None, **kwargs):
        super(Job, self).__init__()
        self._scheduler = scheduler
        self._jobstore_alias = None
        self._modify(id=id or uuid4().hex, **kwargs)

    def modify(self, **changes):
        """
        Makes the given changes to this job and saves it in the associated job store.
        Accepted keyword arguments are the same as the variables on this class.

        .. seealso:: :meth:`~apscheduler.schedulers.base.BaseScheduler.modify_job`
        """

        self._scheduler.modify_job(self.id, self._jobstore_alias, **changes)

    def reschedule(self, trigger, **trigger_args):
        """
        Shortcut for switching the trigger on this job.

        .. seealso:: :meth:`~apscheduler.schedulers.base.BaseScheduler.reschedule_job`
        """

        self._scheduler.reschedule_job(self.id, self._jobstore_alias, trigger, **trigger_args)

    def pause(self):
        """
        Temporarily suspend the execution of this job.

        .. seealso:: :meth:`~apscheduler.schedulers.base.BaseScheduler.pause_job`
        """

        self._scheduler.pause_job(self.id, self._jobstore_alias)

    def resume(self):
        """
        Resume the schedule of this job if previously paused.

        .. seealso:: :meth:`~apscheduler.schedulers.base.BaseScheduler.resume_job`
        """

        self._scheduler.resume_job(self.id, self._jobstore_alias)

    def remove(self):
        """
        Unschedules this job and removes it from its associated job store.

        .. seealso:: :meth:`~apscheduler.schedulers.base.BaseScheduler.remove_job`
        """

        self._scheduler.remove_job(self.id, self._jobstore_alias)

    @property
    def pending(self):
        """Returns ``True`` if the referenced job is still waiting to be added to its designated job store."""

        return self._jobstore_alias is None

    #
    # Private API
    #

    def _get_run_times(self, now):
        """
        Computes the scheduled run times between ``next_run_time`` and ``now`` (inclusive).

        :type now: datetime.datetime
        :rtype: list[datetime.datetime]
        """

        run_times = []
        next_run_time = self.next_run_time
        while next_run_time and next_run_time <= now:
            run_times.append(next_run_time)
            next_run_time = self.trigger.get_next_fire_time(next_run_time, now)

        return run_times

    def _modify(self, **changes):
        """Validates the changes to the Job and makes the modifications if and only if all of them validate."""

        approved = {}

        if 'id' in changes:
            value = changes.pop('id')
            if not isinstance(value, six.string_types):
                raise TypeError("id must be a nonempty string")
            if hasattr(self, 'id'):
                raise ValueError('The job ID may not be changed')
            approved['id'] = value

        if 'func' in changes or 'args' in changes or 'kwargs' in changes:
            func = changes.pop('func') if 'func' in changes else self.func
            args = changes.pop('args') if 'args' in changes else self.args
            kwargs = changes.pop('kwargs') if 'kwargs' in changes else self.kwargs

            if isinstance(func, str):
                func_ref = func
                func = ref_to_obj(func)
            elif callable(func):
                try:
                    func_ref = obj_to_ref(func)
                except ValueError:
                    # If this happens, this Job won't be serializable
                    func_ref = None
            else:
                raise TypeError('func must be a callable or a textual reference to one')

            if not hasattr(self, 'name') and changes.get('name', None) is None:
                changes['name'] = get_callable_name(func)

            if isinstance(args, six.string_types) or not isinstance(args, Iterable):
                raise TypeError('args must be a non-string iterable')
            if isinstance(kwargs, six.string_types) or not isinstance(kwargs, Mapping):
                raise TypeError('kwargs must be a dict-like object')

            check_callable_args(func, args, kwargs)

            approved['func'] = func
            approved['func_ref'] = func_ref
            approved['args'] = args
            approved['kwargs'] = kwargs

        if 'name' in changes:
            value = changes.pop('name')
            if not value or not isinstance(value, six.string_types):
                raise TypeError("name must be a nonempty string")
            approved['name'] = value

        if 'misfire_grace_time' in changes:
            value = changes.pop('misfire_grace_time')
            if value is not None and (not isinstance(value, six.integer_types) or value <= 0):
                raise TypeError('misfire_grace_time must be either None or a positive integer')
            approved['misfire_grace_time'] = value

        if 'coalesce' in changes:
            value = bool(changes.pop('coalesce'))
            approved['coalesce'] = value

        if 'max_instances' in changes:
            value = changes.pop('max_instances')
            if not isinstance(value, six.integer_types) or value <= 0:
                raise TypeError('max_instances must be a positive integer')
            approved['max_instances'] = value

        if 'trigger' in changes:
            trigger = changes.pop('trigger')
            if not isinstance(trigger, BaseTrigger):
                raise TypeError('Expected a trigger instance, got %s instead' % trigger.__class__.__name__)

            approved['trigger'] = trigger

        if 'executor' in changes:
            value = changes.pop('executor')
            if not isinstance(value, six.string_types):
                raise TypeError('executor must be a string')
            approved['executor'] = value

        if 'next_run_time' in changes:
            value = changes.pop('next_run_time')
            approved['next_run_time'] = convert_to_datetime(value, self._scheduler.timezone, 'next_run_time')

        if changes:
            raise AttributeError('The following are not modifiable attributes of Job: %s' % ', '.join(changes))

        for key, value in six.iteritems(approved):
            setattr(self, key, value)

    def __getstate__(self):
        # Don't allow this Job to be serialized if the function reference could not be determined
        if not self.func_ref:
            raise ValueError('This Job cannot be serialized since the reference to its callable (%r) could not be '
                             'determined. Consider giving a textual reference (module:function name) instead.' %
                             (self.func,))

        return {
            'version': 1,
            'id': self.id,
            'func': self.func_ref,
            'trigger': self.trigger,
            'executor': self.executor,
            'args': self.args,
            'kwargs': self.kwargs,
            'name': self.name,
            'misfire_grace_time': self.misfire_grace_time,
            'coalesce': self.coalesce,
            'max_instances': self.max_instances,
            'next_run_time': self.next_run_time
        }

    def __setstate__(self, state):
        if state.get('version', 1) > 1:
            raise ValueError('Job has version %s, but only version 1 can be handled' % state['version'])

        self.id = state['id']
        self.func_ref = state['func']
        self.func = ref_to_obj(self.func_ref)
        self.trigger = state['trigger']
        self.executor = state['executor']
        self.args = state['args']
        self.kwargs = state['kwargs']
        self.name = state['name']
        self.misfire_grace_time = state['misfire_grace_time']
        self.coalesce = state['coalesce']
        self.max_instances = state['max_instances']
        self.next_run_time = state['next_run_time']

    def __eq__(self, other):
        if isinstance(other, Job):
            return self.id == other.id
        return NotImplemented

    def __repr__(self):
        return '<Job (id=%s name=%s)>' % (repr_escape(self.id), repr_escape(self.name))

    def __str__(self):
        return '%s (trigger: %s, next run at: %s)' % (repr_escape(self.name), repr_escape(str(self.trigger)),
                                                      datetime_repr(self.next_run_time))

    def __unicode__(self):
        return six.u('%s (trigger: %s, next run at: %s)') % (self.name, self.trigger, datetime_repr(self.next_run_time))
