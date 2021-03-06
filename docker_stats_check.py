#!/usr/bin/env python
"""Rackspace Cloud Monitoring Plugin for Docker Stats."""

# Copyright 2015 Nachiket Torwekar <nachiket.torwekar@rackspace.com>
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# -----
#
# This plugin monitors the Docker containers via the 'docker stats' command.
# By default the monitor fails if the check does not complete successfully.
# Metrics for:
#
# - cpu_total_usage
# - cpu_system_usage
# - cpu_kernel_mode_usage
# - cpu_user_mode_usage
# - cpu_user_mode_usage
# - memory_max_usage
# - memory_total_cache
# - network_rx_bytes
# - network_rx_packets
# - network_tx_bytes
# - network_tx_packets
#
# are also reported.
#
# Requires:
# Python 2.6 or greater
# docker-py: https://github.com/docker/docker-py
#
# Usage:
# Place script in /usr/lib/rackspace-monitoring-agent/plugins.
# Ensure file is executable (755).
#
# Set up a Cloud Monitoring Check of type agent.plugin to run
#
# docker_stats_check.py -u <URL> -c <container>
#
# The URL is optional and can be a TCP or Unix socket, e.g.
#
# docker_stats_check.py -u tcp://0.0.0.0:2376
# or
# docker_stats_check.py -u unix://var/run/docker.sock
#
# The default URL is unix://var/run/docker.sock.
#
# The container can be name or id
# docker_stats_check.py -u unix://var/run/docker.sock -c agitated_leakey
# or
# docker_stats_check.py -u unix://var/run/docker.sock -c 1f3b3b8f0fcc
#
# There is no need to define specific custom alert criteria.
# As stated, the monitor fails if the stats cannot be collected.
# It is possible to define custom alert criteria with the reported
# metrics if desired.
#

import sys
import docker
from optparse import OptionParser
from subprocess import call
import json

class DockerService(object):
    """Create an object for a Docker service. Assume it is stopped."""

    def __init__(self, url, container):

        self.url = url
        self.container = container
        self.docker_running = False

    def docker_stats(self):
        """Connect to the Docker object and get stats. Error out on failure."""

        try:
            if hasattr(docker, 'Client'):
                # Docker-py 1.x branch
                docker_conn = docker.Client(base_url=self.url)
                stats = docker_conn.stats(self.container)
            elif hasattr(docker, 'DockerClient'):
                # Docker-py 2.x branch
                docker_conn = docker.DockerClient(base_url=self.url)
                stats_gen = docker_conn.containers.get(self.container).stats()
                stats_gen.next() # skip first because it has zeroed precpu_stats
                stats = [ stats_gen.next() ]
            else:
                print "docker_stats_check.py: unsupported version of Docker-py library '%s' (supported are 1.x and 2.x)" % docker.version
                sys.exit(1)
            self.docker_running = True
        # Apologies for the broad exception, it just works here.
        except Exception:
            self.docker_running = False

        if self.docker_running:
            print 'status ok succeeded in obtaining docker container stats.'
            for stat in stats:
                s = json.loads(stat)
                print 'metric cpu_total_usage int64', s['cpu_stats']['cpu_usage']['total_usage']
                print 'metric cpu_system_usage int64', s['cpu_stats']['system_cpu_usage']
                if s['precpu_stats'] and s['precpu_stats'].has_key('cpu_usage') and s['precpu_stats']['cpu_usage'].has_key('total_usage'):
                    print 'metric cpu_usage_percent int64 %.2f' % get_cpu_percentage(s['cpu_stats'], s['precpu_stats'])
                print 'metric cpu_kernel_mode_usage int64', s['cpu_stats']['cpu_usage']['usage_in_kernelmode']
                print 'metric cpu_user_mode_usage int64', s['cpu_stats']['cpu_usage']['usage_in_usermode']
                print 'metric memory_usage int64', s['memory_stats']['usage']
                if s['memory_stats'].has_key('limit'):
                    print 'metric memory_usage_percent int64 %.1f' % (100.0*(float(s['memory_stats']['usage']) / float(s['memory_stats']['limit'])))
                print 'metric memory_max_usage int64', s['memory_stats']['max_usage']
                print 'metric memory_total_cache int64', s['memory_stats']['stats']['total_cache']
                print 'metric pids_current int64', s['pids_stats']['current']
                if s.has_key('network'):
                    print_network_stat(s['network'])
                elif s.has_key('networks'):
                    tot = { "rx_bytes": 0, "rx_packets": 0, "tx_bytes": 0, "tx_packets": 0 }
                    for ifname in s['networks']:
                        tot['rx_bytes'] += s['networks'][ifname]['rx_bytes']
                        tot['rx_packets'] += s['networks'][ifname]['rx_packets']
                        tot['tx_bytes'] += s['networks'][ifname]['tx_bytes']
                        tot['tx_packets'] += s['networks'][ifname]['tx_packets']
                        print_network_stat(s['networks'][ifname], suffix='_' + ifname)
                    print_network_stat(tot)

                sys.exit(0);
        else:
            print 'status err failed to obtain docker container stats.'
            sys.exit(1)

def get_cpu_percentage(c, p):
    """
        Adapted from https://github.com/moby/moby/blob/eb131c5383db8cac633919f82abad86c99bffbe5/cli/command/container/stats_helpers.go#L175
        See https://github.com/moby/moby/issues/29306
    """
    cpuPercent = 0.0
    cpuDelta = float(c['cpu_usage']['total_usage']) - float(p['cpu_usage']['total_usage'])
    systemDelta = float(c['system_cpu_usage']) - float(p['system_cpu_usage'])
    if cpuDelta > 0.0 and systemDelta > 0.0:
        cpuPercent = (cpuDelta / systemDelta) * float(len(p['cpu_usage']['percpu_usage'])) * 100.0
    return cpuPercent

def print_network_stat(n, suffix=''):
    print "metric network_rx_bytes%s int64 %d" % (suffix, n['rx_bytes'])
    print "metric network_rx_packets%s int64 %d" % (suffix, n['rx_packets'])
    print "metric network_tx_bytes%s int64 %d" % (suffix, n['tx_bytes'])
    print "metric network_tx_packets%s int64 %d" % (suffix, n['tx_packets'])


def main():
    """Instantiate a DockerStats object and collect stats."""

    parser = OptionParser()
    parser.add_option('-u', '--url', default='unix://var/run/docker.sock',
                      help='URL for Docker service (Unix or TCP socket).')
    parser.add_option('-c', '--container',
                      help='Name or Id of container that you want to monitor')
    (opts, args) = parser.parse_args()
    if opts.container is None:
        parser.error("options -c is mandatory")

    docker_service = DockerService(opts.url, opts.container)
    docker_service.docker_stats()

if __name__ == '__main__':
    main()