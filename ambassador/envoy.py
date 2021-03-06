import copy
import json
import logging
import os
import time

import dpath
import requests

TOKEN = open("/var/run/secrets/kubernetes.io/serviceaccount/token", "r").read()
SERVICE_URL = "https://kubernetes/api/v1/namespaces/default/services"

def percentage(x, y):
    if y == 0:
        return 0
    else:
        return int(((x * 100) / y) + 0.5)


class TLSConfig (object):
    def __init__(self, chain_env, chain_default_path, privkey_env, privkey_default_path):
        self.chain_path = os.environ.get(chain_env, chain_default_path)
        self.privkey_path = os.environ.get(privkey_env, privkey_default_path)

    def check_file(self, path):
        found = False

        try:
            statinfo = os.stat(path)
            found = True
        except FileNotFoundError:
            pass

        return found

    def config_block(self):
        if (self.check_file(self.chain_path) and
            self.check_file(self.privkey_path)):
            return {
                "cert_chain_file": self.chain_path,
                "private_key_file": self.privkey_path
            }
        else:
            return {}


class EnvoyConfig (object):
    route_template = '''
    {{
        "timeout_ms": 0,
        "prefix": "{url_prefix}",
        "prefix_rewrite": "{rewrite_prefix_as}",
        "cluster": "{cluster_name}"
    }}
    '''

    # We may append the 'features' element to the cluster definition, too.
    #
    # We can switch back to SDS later.
    # "type": "sds",
    # "service_name": "{service_name}",
    #
    # At that time we'll need to reinstate the SDS cluster in envoy-template.json:
    #
    # "sds": {
    #   "cluster": {
    #     "name": "ambassador-sds",
    #     "connect_timeout_ms": 250,
    #     "type": "strict_dns",
    #     "lb_type": "round_robin",
    #     "hosts": [
    #       {
    #         "url": "tcp://ambassador-sds:5000"
    #       }
    #     ]
    #   },
    #   "refresh_delay_ms": 15000
    # },

    cluster_template = '''
    {{
        "name": "{cluster_name}",
        "connect_timeout_ms": 250,
        "lb_type": "round_robin",
        "type": "strict_dns",
        "hosts": []
    }}
    '''

    host_template = '''
    {{
        "url": "tcp://{service_name}:{port}"
    }}
    '''

    self_routes = [
        {
            "timeout_ms": 0,
            "prefix": "/ambassador/",
            "cluster": "ambassador_cluster"
        },
        {
            "timeout_ms": 0,
            "prefix": "/ambassador-config/",
            "prefix_rewrite": "/",
            "cluster": "ambassador_config_cluster"
        }
    ]

    self_clusters = [
        {
            "name": "ambassador_cluster",
            "connect_timeout_ms": 250,
            "type": "static",
            "lb_type": "round_robin",
            "hosts": [
                {
                    "url": "tcp://127.0.0.1:5000"
                }
            ]
        },
        {
            "name": "ambassador_config_cluster",
            "connect_timeout_ms": 250,
            "type": "static",
            "lb_type": "round_robin",
            "hosts": [
                {
                    "url": "tcp://127.0.0.1:8001"
                }
            ]
        }
    ]

    def __init__(self, base_config, tls_config):
        self.mappings = {}
        self.base_config = base_config
        self.tls_config = tls_config

    def add_mapping(self, name, prefix, service, rewrite):
        self.mappings[name] = {
            'prefix': prefix,
            'service': service,
            'rewrite': rewrite
        }

    def write_config(self, path):
        # Generate routes and clusters.
        routes = copy.deepcopy(EnvoyConfig.self_routes)
        clusters = copy.deepcopy(EnvoyConfig.self_clusters)

        logging.info("writing Envoy config to %s" % path)
        logging.info("initial routes: %s" % routes)
        logging.info("initial clusters: %s" % clusters)

        # Grab service info from Kubernetes.
        r = requests.get(SERVICE_URL, headers={"Authorization": "Bearer " + TOKEN}, 
                         verify=False)

        if r.status_code != 200:
            # This can't be good.
            raise Exception("couldn't query Kubernetes for services! %s" % r)

        services = r.json()

        items = services.get('items', [])

        service_info = {}

        for item in items:
            service_name = None
            portspecs = []

            try:
                service_name = dpath.util.get(item, "/metadata/name")
            except KeyError:
                pass

            try:
                portspecs = dpath.util.get(item, "/spec/ports")
            except KeyError:
                pass

            if service_name and portspecs:
                service_info[service_name] = portspecs

        for mapping_name in self.mappings.keys():
            # Does this mapping refer to a service that we know about?
            mapping = self.mappings[mapping_name]
            prefix = mapping['prefix']
            service_name = mapping['service']
            rewrite = mapping['rewrite']

            if service_name in service_info:
                portspecs = service_info[service_name]

                logging.info("mapping %s: pfx %s => svc %s, portspecs %s" % 
                             (mapping_name, prefix, service_name, portspecs))

                host_defs = []

                for portspec in portspecs:
                    pspec = { "service_name": service_name }
                    pspec.update(portspec)

                    host_defs.append(EnvoyConfig.host_template.format(**pspec))

                host_json = "[" + ",".join(host_defs) + "]"
                cluster_hosts = json.loads(host_json)

                # NOTE WELL: the cluster is named after the MAPPING, for flexibility.
                service_def = {
                    'service_name': service_name,
                    'url_prefix': prefix,
                    'rewrite_prefix_as': rewrite,
                    'cluster_name': '%s_cluster' % mapping_name # NOT A TYPO, see above
                }

                route_json = EnvoyConfig.route_template.format(**service_def)
                route = json.loads(route_json)
                logging.info("add route %s" % route)
                routes.append(route)

                cluster_json = EnvoyConfig.cluster_template.format(**service_def)

                cluster = json.loads(cluster_json)
                cluster['hosts'] = cluster_hosts

                logging.info("add cluster %s" % cluster)
                clusters.append(cluster)

        config = copy.deepcopy(self.base_config)

        logging.info("final routes: %s" % routes)
        logging.info("final clusters: %s" % clusters)

        dpath.util.set(
            config,
            "/listeners/0/filters/0/config/route_config/virtual_hosts/0/routes", 
            routes
        )

        dpath.util.set(
            config,
            "/cluster_manager/clusters",
            clusters
        )

        ssl_context = self.tls_config.config_block()

        if ssl_context:
            dpath.util.new(
                config,
                "/listeners/0/ssl_context",
                ssl_context
            )

            dpath.util.set(
                config,
                "/listeners/0/address",
                "tcp://0.0.0.0:443"
            )

        output_file = open(path, "w")

        json.dump(config, output_file, 
                  indent=4, separators=(',',':'), sort_keys=True)
        output_file.write('\n')
        output_file.close()


class EnvoyStats (object):
    def __init__(self):
        self.update_errors = 0
        self.stats = {
            "last_update": 0,
            "last_attempt": 0,
            "update_errors": 0,
            "services": {},
            "envoy": {}
        }

    def update(self, active_mapping_names):
        # Remember how many update errors we had before...
        update_errors = self.stats['update_errors']

        # ...and remember when we started.
        last_attempt = time.time()

        r = requests.get("http://127.0.0.1:8001/stats")

        if r.status_code != 200:
            logging.warning("EnvoyStats.update failed: %s" % r.text)
            self.stats['update_errors'] += 1
            return

        # Parse stats into a hierarchy.

        envoy_stats = {}

        for line in r.text.split("\n"):
            if not line:
                continue

            # logging.info('line: %s' % line)
            key, value = line.split(":")
            keypath = key.split('.')

            node = envoy_stats

            for key in keypath[:-1]:
                if key not in node:
                    node[key] = {}

                node = node[key]

            node[keypath[-1]] = int(value.strip())

        # Now dig into clusters a bit more.

        active_mappings = {}

        if "cluster" in envoy_stats:
            active_cluster_map = {
                x + '_cluster': x
                for x in active_mapping_names
            }

            for cluster_name in envoy_stats['cluster']:
                cluster = envoy_stats['cluster'][cluster_name]

                if cluster_name in active_cluster_map:
                    mapping_name = active_cluster_map[cluster_name]
                    active_mappings[mapping_name] = {}

                    logging.info("SVC %s has cluster" % mapping_name)

                    healthy_members = cluster['membership_healthy']
                    total_members = cluster['membership_total']
                    healthy_percent = percentage(healthy_members, total_members)

                    update_attempts = cluster['update_attempt']
                    update_successes = cluster['update_success']
                    update_percent = percentage(update_successes, update_attempts)

                    upstream_ok = cluster.get('upstream_rq_2xx', 0)
                    upstream_4xx = cluster.get('upstream_rq_4xx', 0)
                    upstream_5xx = cluster.get('upstream_rq_5xx', 0)
                    upstream_bad = upstream_4xx + upstream_5xx

                    active_mappings[mapping_name] = {
                        'healthy_members': healthy_members,
                        'total_members': total_members,
                        'healthy_percent': healthy_percent,

                        'update_attempts': update_attempts,
                        'update_successes': update_successes,
                        'update_percent': update_percent,

                        'upstream_ok': upstream_ok,
                        'upstream_4xx': upstream_4xx,
                        'upstream_5xx': upstream_5xx,
                        'upstream_bad': upstream_bad
                    }

        # OK, we're now officially finished with all the hard stuff.
        last_update = time.time()

        self.stats = {
            "last_update": last_update,
            "last_attempt": last_attempt,
            "update_errors": update_errors,
            "mappings": active_mappings,
            "envoy": envoy_stats
        }
