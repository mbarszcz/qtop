import re
import sys
import os
try:
    import ujson as json
except ImportError:
    import json

import yaml_parser as yaml
from constants import *
from common_module import logging, check_empty_file, options, anonymize_func


# def get_queues_info(fn, write_method):
#     return read_qstatq_yaml(fn_write_method)

def _read_qstatq_yaml(fn, write_method=options.write_method):
    """
    Reads the generated qstatq yaml file and extracts
    the information necessary for building the
    user accounts and pool mappings table.
    """
    qstatq_list = []
    logging.debug("Opening %s" % fn)
    with open(fn, 'r') as fin:
        qstatqs_total = (write_method.endswith('yaml')) and yaml.load_all(fin) or json.load(fin)
        for qstatq in qstatqs_total:
            qstatq_list.append(qstatq)
        total = qstatq_list.pop()
        total_running_jobs, total_queued_jobs = total['Total_running'], total['Total_queued']
    return int(eval(total_running_jobs)), int(eval(total_queued_jobs)), qstatq_list


def _get_worker_nodes(fn, write_method=options.write_method):
    worker_nodes = _read_pbsnodes_yaml(fn, write_method)
    return worker_nodes


def convert_pbsnodes_to_yaml(orig_file, out_file, write_method):
    """
    reads PBSNODES_ORIG_FN sequentially and puts its information into a new yaml file
    """
    all_pbs_values = _get_pbsnodes_values(orig_file, out_file, write_method)
    _pbsnodes_dump_all(all_pbs_values, out_file, pbsnodes_savemethod_mapping[write_method])


def _get_pbsnodes_values(orig_file, out_file, write_method):
    check_empty_file(orig_file)
    raw_blocks = _read_all_blocks(orig_file)
    all_pbs_values = []
    anonymize = anonymize_func()
    for block in raw_blocks:
        pbs_values = dict()
        pbs_values['domainname'] = block['domainname'] if not options.ANONYMIZE else anonymize(block['domainname'], 'wns')

        nextchar = block['state'][0]
        state = (nextchar == 'f') and "-" or nextchar

        pbs_values['state'] = state
        try:
            pbs_values['np'] = block['np']
        except KeyError:
            pbs_values['np'] = block['pcpus']  # handle torque cases  # todo : to check

        if block.get('gpus') > 0:  # this should be rare.
            pbs_values['gpus'] = block['gpus']
        try:  # this should turn up more often, hence the try/except.
            _ = block['jobs']
        except KeyError:
            pass
        else:
            pbs_values['core_job_map'] = []
            jobs = block['jobs'].split(',')
            for job, core in _get_jobs_cores(jobs):
                _d = dict()
                _d['job'] = job
                _d['core'] = core
                pbs_values['core_job_map'].append(_d)
        finally:
            all_pbs_values.append(pbs_values)
    return all_pbs_values


def _pbsnodes_write_lines(l, fout):
    for _block in l:
        fout.write('---\n')
        fout.write('domainname: ' + _block['domainname'] + '\n')
        fout.write('state: ' + _block['state'] + '\n')
        fout.write('np: ' + _block['np'] + '\n')
        if _block.get('gpus') > 0:
            fout.write('gpus: ' + _block['gpus'] + '\n')
        try:  # this should turn up more often, hence the try/except.
            core_job_map = _block['core_job_map']
        except KeyError:
            pass
        else:
            _write_jobs_cores(core_job_map, fout)
        fout.write('...\n')


def _write_jobs_cores(job_cores, fout):
    fout.write('core_job_map: \n')
    # for job, core in get_jobs_cores(jobs):
    for job_core in job_cores:
        fout.write('  - core: ' + job_core['core'] + '\n')
        fout.write('    job: ' + job_core['job'] + '\n')


def _get_jobs_cores(jobs):  # block['jobs']
    """
    Generator that takes str of this format
    '0/10102182.f-batch01.grid.sinica.edu.tw, 1/10102106.f-batch01.grid.sinica.edu.tw, 2/10102339.f-batch01.grid.sinica.edu.tw, 3/10104007.f-batch01.grid.sinica.edu.tw'
    and spits tuples of the format (job,core)
    """
    # jobs = jobs_str.split(',')
    for core_job in jobs:
        core, job = core_job.strip().split('/')
        # core, job = job['core'], job['job']
        if len(core) > len(job):  # PBS vs torque?
            core, job = job, core
        job = job.strip().split('/')[0].split('.')[0]
        yield job, core


def _read_all_blocks(orig_file):
    """
    reads pbsnodes txt file block by block
    """
    with open(orig_file, mode='r') as fin:
        result = []
        reading = True
        while reading:
            wn_block = _read_block(fin)
            if wn_block:
                result.append(wn_block)
            else:
                reading = False
    return result


def _read_block(fin):
    domain_name = fin.readline().strip()
    if not domain_name:
        return None

    block = {'domainname': domain_name}
    reading = True
    while reading:
        line = fin.readline()
        if line == '\n':
            reading = False
        else:
            try:
                key, value = line.split(' = ')
            except ValueError:  # e.g. if line is 'jobs =' with no jobs
                pass
            else:
                block[key.strip()] = value.strip()
    return block


def _pbsnodes_dump_all(l, out_file, write_func_args):
    """
    dumps the content of pbsnodes files with the the selected write_method format
    """
    with open(out_file, 'w') as fout:
        write_func, kwargs, _ = write_func_args
        write_func(l, fout, **kwargs)


def _process_line(re_search, line, re_match_positions):
    qstat_values = dict()
    m = re.search(re_search, line.strip())
    job_id, user, job_state, queue = [m.group(x) for x in re_match_positions]
    job_id = job_id.split('.')[0]
    for key, value in [('JobId', job_id), ('UnixAccount', user), ('S', job_state), ('Queue', queue)]:
        qstat_values[key] = value
    return qstat_values


def _read_pbsnodes_yaml(fn, write_method):
    """
    Parses the pbsnodes yaml file
    :param fn: str
    :return: list
    """
    pbs_nodes = []

    with open(fn) as fin:
        _nodes = (write_method.endswith('yaml')) and yaml.load_all(fin) or json.load(fin)
        for node in _nodes:
            pbs_nodes.append(node)
    # pbs_nodes.pop() if not pbs_nodes[-1] else None # until i figure out why the last node is None
    # this doesn't seem to be the case anymore, DONT KNOW WHY!!
    return pbs_nodes


pbsnodes_savemethod_mapping = {
    'txtyaml': (_pbsnodes_write_lines, {}, 'yaml'),
    'json': (json.dump, {}, 'json')
}
