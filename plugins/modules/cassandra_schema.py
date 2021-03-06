#!/usr/bin/python

# 2020 Rhys Campbell <rhys.james.campbell@googlemail.com>
# https://github.com/rhysmeister
# GNU General Public License v3.0+
# (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)
from __future__ import absolute_import, division, print_function

ANSIBLE_METADATA =\
    {"metadata_version": "1.1",
     "status": "['preview']",
     "supported_by": "community"}

DOCUMENTATION = '''
---
module: cassandra_schema
author: Rhys Campbell (@rhysmeister)
version_added: 2.9
short_description: Validates the schema version as seen from the node.
requirements: [ nodetool ]
description:
    - Validates the schema version as seen from the node.
    - Ensure that all nodes are have the same schema version.
    - Can also specifiy a specific schema version if required.
    - Schema version is obtained thtough the usage of the nodetool describecluster command.
options:
  host:
    description:
      - The hostname.
    type: str
  port:
    description:
      - The Cassandra TCP port.
    type: int
    default: 7199
  password:
    description:
      - The password to authenticate with.
    type: str
  password_file:
    description:
      - Path to a file containing the password.
    type: str
  username:
    description:
      - The username to authenticate with.
    type: str
  uuid:
    description:
      - The expected schema version.
    type: str
    aliases:
      - is
  poll:
    description:
      - The maximum number of times to call nodetool describecluster.
    type: int
    default: 1
  interval:
    description:
      - The number of seconds to wait between poll executions.
    type: int
    default: 30
  nodetool_path:
    description:
      - The path to nodetool.
    type: str
  debug:
    description:
      - Enable additional debug output.
    type: bool
'''

EXAMPLES = '''
- name: Ensure all Cassandra nodes are in schema agreement.
  cassandra_schema:

- name: Ensure all Cassandra nodes have the expected schema version
  cassandra_schema:
    is: 1176b7ac-8993-395d-85fd-41b89ef49fbb

- name: Poll schema version a max of 5 times with a 30 second interval
  cassandra_schema:
    poll: 5
    interval: 30
'''

RETURN = '''
'''

from ansible.module_utils.basic import AnsibleModule, load_platform_subclass
import socket
import re
import time
__metaclass__ = type


class NodeToolCmd(object):
    """
    This is a generic NodeToolCmd class for building nodetool commands
    """

    def __init__(self, module):
        self.module = module
        self.host = module.params['host']
        self.port = module.params['port']
        self.password = module.params['password']
        self.password_file = module.params['password_file']
        self.username = module.params['username']
        self.nodetool_path = module.params['nodetool_path']
        self.debug = module.params['debug']
        if self.host is None:
            self.host = socket.getfqdn()

    def execute_command(self, cmd):
        return self.module.run_command(cmd)

    def nodetool_cmd(self, sub_command):
        if self.nodetool_path is not None and len(self.nodetool_path) > 0 and \
                not self.nodetool_path.endswith('/'):
            self.nodetool_path += '/'
        else:
            self.nodetool_path = ""
        cmd = "{0}nodetool --host {1} --port {2}".format(self.nodetool_path,
                                                         self.host,
                                                         self.port)
        if self.username is not None:
            cmd += " --username {0}".format(self.username)
            if self.password_file is not None:
                cmd += " --password-file {0}".format(self.password_file)
            else:
                cmd += " --password '{0}'".format(self.password)
        # The thing we want nodetool to execute
        cmd += " {0}".format(sub_command)
        if self.debug:
            self.module.debug(cmd)
        return self.execute_command(cmd)


class NodeToolStatusCommand(NodeToolCmd):

    """
    Inherits from the NodeToolCmd class. Adds the following methods;

        - status_command

    """

    def __init__(self, module):
        NodeToolCmd.__init__(self, module)
        self.status_cmd = "describecluster"

    def status_command(self):
        return self.nodetool_cmd(self.status_cmd)


def nodetool_status_poll(module):
    '''
    Calls NodeToolStatusCommand(module, status_cmd) a maximum of poll times
    with the indicated interval. Returns as soon all nodes are up or the
    previous limits are reached.
    '''
    cluster_status = None  # Last cluster status
    cluster_schema_list = []
    iterations = 0
    return_codes = []
    stdout_list = []
    stderr_list = []
    down_running_total = None
    poll = module.params['poll']
    interval = module.params['interval']

    while iterations < poll:
        down_running_total = 0  # reset between iterations
        iterations += 1
        n = NodeToolStatusCommand(module)
        (rc, out, err) = n.status_command()
        stdout_list.append(out.strip())
        stderr_list.append(err.strip())
        return_codes.append(rc)
        if rc == 0:
            schema_status = cluster_schema(out)
            cluster_schema_list.append(schema_status)
            schema_count_total = len(cluster_schema_list)
            if schema_count_total == 1:
                break  # The cluster has one schema... we're good
            else:
                if iterations == poll:
                    break
                else:
                    time.sleep(interval)  # Something is wrong, check again in a bit but
        else:
            if iterations == poll:
                break
            else:
                time.sleep(interval)
    return schema_status, cluster_schema_list, iterations, \
        return_codes, stdout_list, stderr_list, schema_count_total


def cluster_schema(stdout):
    '''
    Extract the scheam version output from the nodetool describecluster stdout
    Returns a dict in the following format...
        {
            "d4f18346-f81f-3786-aed4-40e03558b299:" [127.0.0.1]
        }
    # TODO do something about UNREACHABLE nodes???
    '''
    cluster_up_down = {}
    schema_version_line = False
    schema_version_lines = []
    return_dict = {}

    # match the scmea id and the list of hosts
    regex = r"(\{){0,1}[0-9a-fA-F]{8}\-[0-9a-fA-F]{4}\-[0-9a-fA-F]{4}\-[0-9a-fA-F]{4}\-[0-9a-fA-F]{12}(\}){0,1}: \[.*\]"

    matches = re.finditer(regex, stdout, re.MULTILINE)

    for matchNum, match in enumerate(matches, start=1):

        uuid, host_list = match.group().split(":")
        return_dict[uuid.strip()] = host_list[:-1][1:].split(", ")
        # Should do something about UNREACHABLE entries

    return return_dict


def main():
    module = AnsibleModule(
        argument_spec=dict(
            host=dict(type='str', default=None),
            port=dict(type='int', default=7199),
            password=dict(type='str', no_log=True),
            password_file=dict(type='str', no_log=True),
            username=dict(type='str', no_log=True),
            uuid=dict(type='str', aliases=['is']),
            poll=dict(type='int', default=1),
            interval=dict(type='int', default=30),
            nodetool_path=dict(type='str', default=None, required=False),
            debug=dict(type='bool', default=False, required=False)),
        supports_check_mode=False)

    uuid = module.params['uuid']
    debug = module.params['debug']

    schema_status, cluster_schema_list, iterations, \
        return_codes, stdout_list, stderr_list, schema_count_total \
        = nodetool_status_poll(module)

    result = {}

    result['schema_status'] = schema_status
    if iterations > 1:
        result['iterations'] = iterations

    if debug:
        result['cluster_schema_list'] = cluster_schema_list
        result['return_codes'] = return_codes
        if stderr_list:
            result['stderr_list'] = stderr_list
        if stdout_list:
            result['stdout_list'] = stdout_list

    # Needs rethink
    if return_codes[-1] == 0:  # Last execution successful
        if schema_count_total == 1 and uuid in schema_status.keys():
            result['msg'] = "The cluster has reached consensus with the expected version"
        elif schema_count_total == 1:
            result['msg'] = "The cluster has reached schema consensus"
        else:
            result['msg'] = "The cluster has not reached consensus on the schema"
            module.fail_json(**result)
    else:
        result['msg'] = "nodetool error: {0}".format(stderr_list[-1])
        result['rc'] = return_codes[-1]
        module.fail_json(**result)

    # Everything is good
    module.exit_json(**result)


if __name__ == '__main__':
    main()
