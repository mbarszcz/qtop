__author__ = 'sfranky'
# import yaml
import os
from common_module import *
import yaml_parser as yaml
try:
    from collections import OrderedDict
except ImportError:
    from ordereddict import OrderedDict


# def read_oarnodes_yaml(fn_s, fn_y, write_method):
def _get_worker_nodes(fn_s, fn_y, write_method=options.write_method):
    nodes_resids = _read_oarnodes_s_yaml(fn_s, write_method)
    resids_jobs = _read_oarnodes_y_textyaml(fn_y)

    nodes_jobs = {}
    for node in nodes_resids:
        resids_state_lot = nodes_resids[node]
        for (resid, state) in resids_state_lot:
                nodes_jobs.setdefault(node, []).append((resids_jobs[int(resid)], state))

    worker_nodes = list()
    #todo: make user-tuneable
    node_state_mapping = {'Alive': '-', 'Dead': 'd', 'Suspected': 's', 'Mixed': '%'}
    for node in nodes_jobs:
        d = OrderedDict()
        d['domainname'] = node
        nr_of_jobs = len(nodes_jobs[node])
        d['np'] = nr_of_jobs
        d['core_job_map'] = [{'core': idx, 'job': job[0]} for idx, job in enumerate(nodes_jobs[node]) if job[0] is not None]
        if not d['core_job_map']:
            del d['core_job_map']
        d['state'] = _calculate_oar_state(nodes_jobs[node], nr_of_jobs, node_state_mapping)
        worker_nodes.append(d)

    logging.info('worker_nodes contains %s entries' % len(worker_nodes))
    return worker_nodes


class OarStatMaker(QStatMaker):
    def __init__(self, config):
        StatMaker.__init__(self, config)
        self.user_q_search = r'^(?P<job_id>[0-9]+)\s+' \
                             r'(?P<name>[0-9A-Za-z_.-]+)?\s+' \
                             r'(?P<user>[0-9A-Za-z_.-]+)\s+' \
                             r'(?:\d{4}-\d{2}-\d{2})\s+' \
                             r'(?:\d{2}:\d{2}:\d{2})\s+' \
                             r'(?P<job_state>[RWF])\s+' \
                             r'(?P<queue>default|besteffort)'

    def convert_qstat_to_yaml(self, orig_file, out_file, write_method):
        with open(orig_file, 'r') as fin:
            logging.debug('File state before OarStatMaker.convert_qstat_to_yaml: %(fin)s' % {"fin": fin})
            _ = fin.readline()  # header
            fin.readline()  # dashes
            re_match_positions = ('job_id', 'user', 'job_state', 'queue')
            re_search = self.user_q_search
            for line in fin:
                qstat_values = self.process_line(re_search, line, re_match_positions)
                self.l.append(qstat_values)

        logging.debug('File state after OarStatMaker.convert_qstat_to_yaml: %(fin)s' % {"fin": fin})
        self.dump_all(out_file, self.stat_mapping[write_method])


# def get_queues_info(fn, write_method):
#     return lambda *args, **kwargs: (0, 0, [])

def _read_oarnodes_s_yaml(fn_s, write_method):  # todo: fix write_method not being used
    assert os.path.isfile(fn_s)
    anonymize = anonymize_func()
    logging.debug('File %s exists: %s' % (fn_s, os.path.isfile(fn_s)))
    try:
        assert os.stat(fn_s).st_size != 0
    except AssertionError:
        logging.critical('File %s is empty!! Exiting...\n' % fn_s)
        raise
    data = yaml.safe_load(fn_s, DEF_INDENT=4)
    if options.ANONYMIZE:
        nodes_resids = dict([(anonymize(node, 'wns'), list(resid_state.items())) for node, resid_state in list(data.items())])
    else:
        nodes_resids = dict([(node, list(resid_state.items())) for node, resid_state in list(data.items())])
    # import wdb; wdb.set_trace()
    return nodes_resids


def _read_oarnodes_y_yaml(fn_y):
    with open('oarnodes_y', mode='r') as fin:
        data = yaml.load(fin)
    resids_jobs = dict([(resid, info.get('jobs', None)) for resid, info in list(data.items())])
    return resids_jobs


def _read_oarnodes_y_textyaml(fn):
    oar_nodes = {}
    logging.debug("Before opening %s" % fn)
    with open(fn, mode='r') as fin:
        logging.debug("File state %s" % fin)
        fin.readline()  # '---'
        line = fin.readline().strip()  # first res_id
        while line:
            oar_node, line = _read_oar_node_y_textyaml(fin, line)
            oar_nodes.update(oar_node)

        resids_jobs = dict([(resid, info.get('jobs', None)) for resid, info in list(oar_nodes.items())])
    return resids_jobs
    # return oar_nodes


def _read_oar_node_y_textyaml(fin, line):
    _oarnode = dict()

    res_id = line.strip(': ')
    _oarnode[int(res_id)] = dict()

    line = fin.readline().strip()
    while line and not line[0].isdigit():
        key, value = line.strip().split(': ')
        _oarnode[int(res_id)][key] = value
        line = fin.readline().strip()

    return _oarnode, line


def _calculate_oar_state(jobid_state_lot, nr_of_jobs, node_state_mapping):
    """
    If all resource ids within the node are either alive or dead or suspected, the respective label is given to the node.
    Otherwise, a mixed-state is reported
    """
    #todo: make user-tuneable
    states = [job_state_tpl[1] for job_state_tpl in jobid_state_lot]
    alive = states.count('Alive')
    dead = states.count('Dead')
    suspected = states.count('Suspected')

    if bool(alive) + bool(dead) + bool(suspected) > 1:
        state = node_state_mapping['Mixed']  # TODO: investigate!
        return state
    else:
        return node_state_mapping[states[0]]
