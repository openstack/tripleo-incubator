#!/usr/bin/env python
#
# Copyright 2014 Hewlett-Packard Development Company, L.P.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import argparse
import json
import os
import subprocess
import sys
import tempfile
import yaml

from heatclient.common import utils
from heatclient import exc
from heatclient.v1 import client as heatclient
from keystoneclient.v2_0 import client as ksclient
import testtools


class FakeHeatClient(object):
    id = None

    def __init__(self, endpoint, **kwargs):
        self.endpoint = endpoint
        self.kwargs = kwargs

    @property
    def stacks(self):
        return self

    @property
    def outputs(self):
        return {'output': 'a special value'}

    def get(self, id):
        self.id = id
        return self


class TestClientNestedStack(testtools.TestCase):
    def test_parses_stack(self):
        template = '''
            resources:
                ParentStack:
                    template: parent.path
                    parameters: ['param1', 'param2']
                    outputs: ['output']
                ChildStack:
                    template: child.path
                    parameters: ['param1', 'param3']
                    inputs: ['output']
            '''
        with tempfile.NamedTemporaryFile() as tf:
            tf.write(template)
            tf.flush()
            main([
                '--template-file', tf.name,
                '--noop',
                'a-stack-name'
            ], heat_client=FakeHeatClient)


def main(argv, heat_client=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--template-file', '-t')
    parser.add_argument('--environment', '-e')
    parser.add_argument('--noop', default=False, action='store_true')
    parser.add_argument('-k', '--insecure',
                        default=False,
                        action='store_true',
                        help="Explicitly allow the client to perform "
                        "\"insecure\" SSL (https) requests. The server's "
                        "certificate will not be verified against any "
                        "certificate authorities. "
                        "This option should be used with caution.")
    parser.add_argument('--os-username',
                        default=utils.env('OS_USERNAME'),
                        help='Defaults to env[OS_USERNAME].')

    parser.add_argument('--os_username',
                        help=argparse.SUPPRESS)

    parser.add_argument('--os-password',
                        default=utils.env('OS_PASSWORD'),
                        help='Defaults to env[OS_PASSWORD].')

    parser.add_argument('--os_password',
                        help=argparse.SUPPRESS)

    parser.add_argument('--os-tenant-id',
                        default=utils.env('OS_TENANT_ID'),
                        help='Defaults to env[OS_TENANT_ID].')

    parser.add_argument('--os_tenant_id',
                        help=argparse.SUPPRESS)

    parser.add_argument('--os-tenant-name',
                        default=utils.env('OS_TENANT_NAME'),
                        help='Defaults to env[OS_TENANT_NAME].')

    parser.add_argument('--os_tenant_name',
                        help=argparse.SUPPRESS)

    parser.add_argument('--os-auth-url',
                        default=utils.env('OS_AUTH_URL'),
                        help='Defaults to env[OS_AUTH_URL].')

    parser.add_argument('--os_auth_url',
                        help=argparse.SUPPRESS)

    parser.add_argument('--os-region-name',
                        default=utils.env('OS_REGION_NAME'),
                        help='Defaults to env[OS_REGION_NAME].')

    parser.add_argument('--os_region_name',
                        help=argparse.SUPPRESS)
    parser.add_argument('--os-service-type',
                        default=utils.env('OS_SERVICE_TYPE'),
                        help='Defaults to env[OS_SERVICE_TYPE].')

    parser.add_argument('--os_service_type',
                        help=argparse.SUPPRESS)

    parser.add_argument('--os-endpoint-type',
                        default=utils.env('OS_ENDPOINT_TYPE'),
                        help='Defaults to env[OS_ENDPOINT_TYPE].')
    parser.add_argument('--os_endpoint_type',
                        help=argparse.SUPPRESS)

    parser.add_argument('--os-cacert',
                        metavar='<ca-certificate>',
                        default=utils.env('OS_CACERT', default=None),
                        help='Specify a CA bundle file to use in '
                        'verifying a TLS (https) server certificate. '
                        'Defaults to env[OS_CACERT]')

    parser.add_argument('name')
    (args, passthrough) = parser.parse_known_args(argv)
    kwargs = {
        'username': args.os_username,
        'password': args.os_password,
        'tenant_id': args.os_tenant_id,
        'tenant_name': args.os_tenant_name,
        'auth_url': args.os_auth_url,
        'service_type': args.os_service_type,
        'endpoint_type': args.os_endpoint_type,
        'insecure': args.insecure,
        'cacert': args.os_cacert,
        'region_name': args.os_region_name,
    }
    ks_client = _get_ksclient(**kwargs)
    kwargs['token'] = ks_client.auth_token
    endpoint = _get_endpoint(ks_client, **kwargs)
    clientlib = heat_client or heatclient.Client
    client = clientlib(endpoint, **kwargs)
    with open(args.template_file) as tf:
        doc = yaml.load(tf, Loader=yaml.CSafeLoader)
    if 'resources' not in doc:
        raise ValueError('Need a mapping with resources')
    stacks = make_stacks(doc, args.environment, args.name)
    data_pool = {}
    # Grab outputs
    for stack in stacks:
        stack.set_id(client)
        stack.fetch_outputs(client, data_pool)
    # set known/desired outputs in environment
    for stack in stacks:
        stack.set_inputs(data_pool)
    # create or update
    for stack in stacks:
        stack.create_or_update(passthrough, noop=args.noop)


def _get_ksclient(**kwargs):
    """Get an endpoint and auth token from Keystone.

    :param username: name of user
    :param password: user's password
    :param tenant_id: unique identifier of tenant
    :param tenant_name: name of tenant
    :param auth_url: endpoint to authenticate against
    :param token: token to use instead of username/password
    """
    kc_args = {'auth_url': kwargs.get('auth_url'),
               'insecure': kwargs.get('insecure'),
               'cacert': kwargs.get('cacert')}

    if kwargs.get('tenant_id'):
        kc_args['tenant_id'] = kwargs.get('tenant_id')
    else:
        kc_args['tenant_name'] = kwargs.get('tenant_name')

    if kwargs.get('token'):
        kc_args['token'] = kwargs.get('token')
    else:
        kc_args['username'] = kwargs.get('username')
        kc_args['password'] = kwargs.get('password')

    return ksclient.Client(**kc_args)


def _get_endpoint(client, **kwargs):
    """Get an endpoint using the provided keystone client."""
    if kwargs.get('region_name'):
        return client.service_catalog.url_for(
            service_type=kwargs.get('service_type') or 'orchestration',
            attr='region',
            filter_value=kwargs.get('region_name'),
            endpoint_type=kwargs.get('endpoint_type') or 'publicURL')
    return client.service_catalog.url_for(
        service_type=kwargs.get('service_type') or 'orchestration',
        endpoint_type=kwargs.get('endpoint_type') or 'publicURL')


class Stack(object):
    def __init__(self, name, master, template, inputs, outputs, aliases, env):
        self.name = name
        self.master = master
        self.template = template
        self.inputs = inputs
        self.outputs = outputs
        self.aliases = aliases
        self.env = env
        self.id = None

    @property
    def full_stack_name(self):
        return '%(master)s%(name)s' % {'master': self.master,
                                       'name': self.name}

    def set_id(self, client):
        if self.id is not None:
            return
        try:
            s = client.stacks.get(self.full_stack_name)
            self.id = s.id
        except exc.HTTPNotFound:
            pass
        except Exception as e:
            print("EXCEPTION!! %s" % type(e))

    def __repr__(self):
        return (
            str('Stack(%(id)s, %(master), %(template)s, %(env)s)'
            % self.__dict__))

    def fetch_outputs(self, client, data_pool):
        if self.id is None or self.outputs is None:
            return
        try:
            outputs = client.stacks.get(self.id).outputs
        except Exception as e:
            print('EXCEPTION in fetch_ouptputs! %s' % str(e))
            return
        for desired_output in self.outputs:
            if desired_output in outputs:
                data_pool[desired_output] = outputs[desired_output]

    def set_inputs(self, data_pool):
        if self.inputs is None:
            return
        for desired_input in self.inputs:
            if desired_input in data_pool:
                val = data_pool[desired_input]
            else:
                val = ''
            self.env[desired_input] = val
            if self.aliases and desired_input in self.aliases:
                for intended_key in self.aliases[desired_input]['aliases']:
                    self.env[intended_key] = val
                if self.aliases[desired_input].get('rename'):
                    del self.env[desired_input]

    def create_or_update(self, passthrough, noop=False):
        with tempfile.NamedTemporaryFile() as new_env_file:
            new_env_file.write(json.dumps({'parameters': self.env}))
            new_env_file.flush()
            if self.id is None:
                cmd = 'stack-create'
            else:
                cmd = 'stack-update'
            args = [
                'heat', cmd,
                '--template-file', self.template,
                '--environment', new_env_file.name,
                self.full_stack_name
            ]
            args.extend(passthrough)
            if noop:
                print('COMMAND: %s' % (' '.join(args)))
            else:
                try:
                    subprocess.check_call(args)
                except subprocess.CalledProcessError as e:
                    print(str(e))
                    print(json.dumps(self.env, indent=1))


def make_stacks(doc, env, master):
    stacks = []
    for name, res in iter(doc['resources'].items()):
        # Only pass named env vars through
        allowed_params = res.get('parameters')
        if not allowed_params:
            # pull from template
            with open(res['template']) as tf:
                tdoc = yaml.load(tf, Loader=yaml.CSafeLoader)
                allowed_params = tdoc.get('Parameters', tdoc.get('parameters', {})).keys()
        if env and os.path.exists(env):
            with open(env) as env_file:
                this_env = json.load(env_file).get('parameters')
                if allowed_params:
                    new_env = dict(
                            [(ekey, edat) for ekey, edat in this_env.items()
                                if ekey in allowed_params])
                else:
                    new_env = dict(this_env)
        else:
            new_env = {}
        s = Stack(
            name,
            master,
            res.get('template'),
            res.get('inputs'),
            res.get('outputs'),
            res.get('aliases'),
            new_env)
        stacks.append(s)
    return stacks

if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
