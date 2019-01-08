#!/usr/bin/env python3

"""
# get_capacity_info.py

Retrieves the capacity of flavors how many instances of each falvor
can be hosted per hypervisor along with total summary.

Copyright 2019 Canonical Ltd

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""

import os
import sys
import yaml


_path = os.path.dirname(os.path.realpath(__file__))
_root = os.path.abspath(os.path.join(_path, '..'))


def _add_path(path):
    if path not in sys.path:
        sys.path.insert(1, path)


_add_path(_root)

import charmhelpers.core.hookenv as hookenv
from charmhelpers.contrib.openstack.context import IdentityServiceContext

try:
    from novaclient import client
    from keystoneauth1.exceptions.http import (
        Unauthorized,
        NotFound,
        BadRequest,
    )
    from keystoneauth1.exceptions.catalog import EndpointNotFound
    from keystoneclient.auth.identity import v2, v3
    from keystoneauth1 import session
except ImportError:
    hookenv.action_set({"importerror": "python3-keystoneclient or "
                        "python3-novaclient packages not available."
                        " Please install those packages"})
    sys.exit(1)
config = hookenv.config()

ram_allocation_ratio = config['ram-allocation-ratio']
cpu_allocation_ratio = config['cpu-allocation-ratio']


def can_host_flavor(hypervisor, flavor,
                    ram_allocation_ratio, cpu_allocation_ratio):
    """ Calculates number of instances
    per flavor from a hypervisor. """
    count = 0
    free_mem = hypervisor.free_ram_mb * ram_allocation_ratio
    free_vcpu = hypervisor.vcpus * cpu_allocation_ratio - hypervisor.vcpus_used
    mem_count = free_mem // flavor.ram
    vcpu_count = free_vcpu // flavor.vcpus
    count = min(mem_count, vcpu_count)
    return int(count)


def get_nova_api():
    """ Retrieves
        nova client session. """
    context = IdentityServiceContext()()
    try:
        api_version = int(context['api_version'])
        if api_version == 2:
            endpoint = "{}://{}:{}/v{}".format(context['service_protocol'],
                                               context['service_host'],
                                               context['service_port'],
                                               float(context['api_version']))
        else:
            endpoint = "{}://{}:{}/v{}".format(context['service_protocol'],
                                               context['service_host'],
                                               context['service_port'],
                                               context['api_version'])
    except KeyError as e:
        hookenv.action_fail(e.message)
        hookenv.action_set(
            {"error": "Did not receive the openstack-auth "
             "parameters from identity context"}
        )
        sys.exit(1)
    nova_api = client.Client(
        '2.2', session=get_auth_session(endpoint, api_version, context))
    return nova_api


def get_auth_session(endpoint, api_version, context):
    """ Gets keystone authentication
    session. """
    if api_version == 2:
        auth = v2.Password(auth_url=endpoint, username=context['admin_user'],
                           password=context['admin_password'],
                           tenant_name=context['admin_tenant_name'])
    elif api_version == 3:
        auth = v3.Password(auth_url=endpoint, username=context['admin_user'],
                           password=context['admin_password'],
                           user_domain_id=context['admin_domain_id'])
    return session.Session(auth=auth)


def main():
    nova = get_nova_api()
    try:
        hypervisors = nova.hypervisors.list()
        flavors = nova.flavors.list()
    except (Unauthorized, NotFound, BadRequest, EndpointNotFound) as e:
        msg = e.message
        hookenv.action_fail(msg)
        hookenv.action_set({"error": " error from api"
                           " {}".format(msg)})
        sys.exit(1)
    output = {"Total_Capacity": {}}
    for flavor in flavors:
        total_instances_per_flavor = 0
        flavor_name = str(flavor.name)
        for hypervisor in hypervisors:
            hostname = str(hypervisor.hypervisor_hostname)
            total_instances = can_host_flavor(hypervisor, flavor,
                                              ram_allocation_ratio,
                                              cpu_allocation_ratio)
            total_instances_per_flavor += total_instances
            if hostname not in output:
                output[hostname] = {}
            output[hostname][flavor_name] = total_instances
        output["Total_Capacity"][flavor_name] = total_instances_per_flavor
    hookenv.action_set({'get-capacity-info': yaml.dump(output)})


if __name__ == "__main__":
    main()

