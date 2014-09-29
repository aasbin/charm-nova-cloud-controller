from mock import MagicMock, patch, call
from test_utils import CharmTestCase, patch_open
import os
with patch('charmhelpers.core.hookenv.config') as config:
    config.return_value = 'neutron'
    import nova_cc_utils as utils

_reg = utils.register_configs
_map = utils.restart_map

utils.register_configs = MagicMock()
utils.restart_map = MagicMock()

with patch('nova_cc_utils.guard_map') as gmap:
    with patch('charmhelpers.core.hookenv.config') as config:
        config.return_value = False
        gmap.return_value = {}
        import nova_cc_hooks as hooks

utils.register_configs = _reg
utils.restart_map = _map

TO_PATCH = [
    'api_port',
    'apt_update',
    'apt_install',
    'canonical_url',
    'configure_installation_source',
    'charm_dir',
    'do_openstack_upgrade',
    'openstack_upgrade_available',
    'cmd_all_services',
    'config',
    'determine_packages',
    'determine_ports',
    'disable_services',
    'enable_services',
    'NovaCellContext',
    'open_port',
    'is_relation_made',
    'local_unit',
    'log',
    'relation_get',
    'relation_set',
    'relation_ids',
    'ssh_compute_add',
    'ssh_known_hosts_lines',
    'ssh_authorized_keys_lines',
    'save_script_rc',
    'service_running',
    'service_stop',
    'execd_preinstall',
    'network_manager',
    'volume_service',
    'unit_get',
    'uuid',
    'eligible_leader',
    'keystone_ca_cert_b64',
    'neutron_plugin',
    'migrate_database',
]


FAKE_KS_AUTH_CFG = {
    'auth_host': 'kshost',
    'auth_port': '5000',
    'service_port': 'token',
    'service_username': 'admin_user',
    'service_password': 'admin_passwd',
    'service_tenant_name': 'admin_tenant',
    'auth_uri': 'http://kshost:5000/v2',
    # quantum-gateway interface deviates a bit.
    'keystone_host': 'kshost',
    'service_tenant': 'service_tenant',
}


class NovaCCHooksTests(CharmTestCase):

    def setUp(self):
        super(NovaCCHooksTests, self).setUp(hooks, TO_PATCH)

        self.config.side_effect = self.test_config.get
        self.relation_get.side_effect = self.test_relation.get
        self.charm_dir.return_value = '/var/lib/juju/charms/nova/charm'

    def test_install_hook(self):
        self.determine_packages.return_value = [
            'nova-scheduler', 'nova-api-ec2']
        self.determine_ports.return_value = [80, 81, 82]
        hooks.install()
        self.apt_install.assert_called_with(
            ['nova-scheduler', 'nova-api-ec2'], fatal=True)
        self.execd_preinstall.assert_called()
        self.disable_services.assert_called()
        self.cmd_all_services.assert_called_with('stop')

    @patch.object(hooks, 'configure_https')
    def test_config_changed_no_upgrade(self, conf_https):
        self.openstack_upgrade_available.return_value = False
        hooks.config_changed()
        self.assertTrue(self.save_script_rc.called)

    @patch.object(hooks, 'configure_https')
    def test_config_changed_with_upgrade(self, conf_https):
        self.openstack_upgrade_available.return_value = True
        hooks.config_changed()
        self.assertTrue(self.do_openstack_upgrade.called)
        self.assertTrue(self.save_script_rc.called)

    def test_compute_changed_ssh_migration(self):
        self.test_relation.set({
            'migration_auth_type': 'ssh', 'ssh_public_key': 'fookey',
            'private-address': '10.0.0.1'})
        self.ssh_known_hosts_lines.return_value = [
            'k_h_0', 'k_h_1', 'k_h_2']
        self.ssh_authorized_keys_lines.return_value = [
            'auth_0', 'auth_1', 'auth_2']
        hooks.compute_changed()
        self.ssh_compute_add.assert_called_with('fookey', rid=None, unit=None)
        expected_relations = [
            call(relation_settings={'authorized_keys_0': 'auth_0'},
                 relation_id=None),
            call(relation_settings={'authorized_keys_1': 'auth_1'},
                 relation_id=None),
            call(relation_settings={'authorized_keys_2': 'auth_2'},
                 relation_id=None),
            call(relation_settings={'known_hosts_0': 'k_h_0'},
                 relation_id=None),
            call(relation_settings={'known_hosts_1': 'k_h_1'},
                 relation_id=None),
            call(relation_settings={'known_hosts_2': 'k_h_2'},
                 relation_id=None),
            call(authorized_keys_max_index=3, relation_id=None),
            call(known_hosts_max_index=3, relation_id=None)]
        self.assertEquals(sorted(self.relation_set.call_args_list),
                          sorted(expected_relations))

    def test_compute_changed_nova_public_key(self):
        self.test_relation.set({
            'migration_auth_type': 'sasl', 'nova_ssh_public_key': 'fookey',
            'private-address': '10.0.0.1'})
        self.ssh_known_hosts_lines.return_value = [
            'k_h_0', 'k_h_1', 'k_h_2']
        self.ssh_authorized_keys_lines.return_value = [
            'auth_0', 'auth_1', 'auth_2']
        hooks.compute_changed()
        self.ssh_compute_add.assert_called_with('fookey', user='nova',
                                                rid=None, unit=None)
        expected_relations = [
            call(relation_settings={'nova_authorized_keys_0': 'auth_0'},
                 relation_id=None),
            call(relation_settings={'nova_authorized_keys_1': 'auth_1'},
                 relation_id=None),
            call(relation_settings={'nova_authorized_keys_2': 'auth_2'},
                 relation_id=None),
            call(relation_settings={'nova_known_hosts_0': 'k_h_0'},
                 relation_id=None),
            call(relation_settings={'nova_known_hosts_1': 'k_h_1'},
                 relation_id=None),
            call(relation_settings={'nova_known_hosts_2': 'k_h_2'},
                 relation_id=None),
            call(relation_settings={'nova_known_hosts_max_index': 3},
                 relation_id=None),
            call(relation_settings={'nova_authorized_keys_max_index': 3},
                 relation_id=None)]
        self.assertEquals(sorted(self.relation_set.call_args_list),
                          sorted(expected_relations))

    @patch.object(utils, 'config')
    @patch.object(hooks, '_auth_config')
    def test_compute_joined_neutron(self, auth_config, _util_config):
        _util_config.return_value = None
        self.is_relation_made.return_value = False
        self.network_manager.return_value = 'neutron'
        self.eligible_leader = True
        self.keystone_ca_cert_b64.return_value = 'foocert64'
        self.volume_service.return_value = 'cinder'
        self.unit_get.return_value = 'nova-cc-host1'
        self.canonical_url.return_value = 'http://nova-cc-host1'
        self.api_port.return_value = '9696'
        self.neutron_plugin.return_value = 'nvp'
        auth_config.return_value = FAKE_KS_AUTH_CFG
        hooks.compute_joined()

        self.relation_set.assert_called_with(
            relation_id=None,
            quantum_url='http://nova-cc-host1:9696',
            ca_cert='foocert64',
            quantum_port=9696,
            quantum_host='nova-cc-host1',
            quantum_security_groups='no',
            region='RegionOne',
            volume_service='cinder',
            ec2_host='nova-cc-host1',
            quantum_plugin='nvp',
            network_manager='neutron', **FAKE_KS_AUTH_CFG)

    @patch.object(utils, 'config')
    @patch.object(hooks, 'NeutronAPIContext')
    @patch.object(hooks, '_auth_config')
    def test_compute_joined_neutron_api_rel(self, auth_config, napi,
                                            _util_config):
        def mock_NeutronAPIContext():
            return {
                'neutron_plugin': 'bob',
                'neutron_security_groups': 'yes',
                'neutron_url': 'http://nova-cc-host1:9696',
            }
        _util_config.return_value = None
        napi.return_value = mock_NeutronAPIContext
        self.is_relation_made.return_value = True
        self.network_manager.return_value = 'neutron'
        self.eligible_leader = True
        self.keystone_ca_cert_b64.return_value = 'foocert64'
        self.volume_service.return_value = 'cinder'
        self.unit_get.return_value = 'nova-cc-host1'
        self.canonical_url.return_value = 'http://nova-cc-host1'
        self.api_port.return_value = '9696'
        self.neutron_plugin.return_value = 'nvp'
        auth_config.return_value = FAKE_KS_AUTH_CFG
        hooks.compute_joined()
        self.relation_set.assert_called_with(
            relation_id=None,
            quantum_url='http://nova-cc-host1:9696',
            ca_cert='foocert64',
            quantum_port=9696,
            quantum_host='nova-cc-host1',
            quantum_security_groups='yes',
            region='RegionOne',
            volume_service='cinder',
            ec2_host='nova-cc-host1',
            quantum_plugin='bob',
            network_manager='neutron', **FAKE_KS_AUTH_CFG)

    @patch.object(hooks, '_auth_config')
    def test_nova_vmware_joined(self, auth_config):
        auth_config.return_value = FAKE_KS_AUTH_CFG
        # quantum-security-groups, plugin
        self.neutron_plugin.return_value = 'nvp'
        self.network_manager.return_value = 'neutron'
        self.canonical_url.return_value = 'http://nova-cc-host1'
        self.api_port.return_value = '9696'
        hooks.nova_vmware_relation_joined()
        self.relation_set.assert_called_with(
            network_manager='neutron', quantum_security_groups='no',
            quantum_url='http://nova-cc-host1:9696', quantum_plugin='nvp',
            relation_id=None,
            **FAKE_KS_AUTH_CFG)

    def test_db_joined(self):
        self.unit_get.return_value = 'nova.foohost.com'
        self.is_relation_made.return_value = False
        hooks.db_joined()
        self.relation_set.assert_called_with(nova_database='nova',
                                             nova_username='nova',
                                             nova_hostname='nova.foohost.com')
        self.unit_get.assert_called_with('private-address')

    def test_postgresql_nova_db_joined(self):
        self.is_relation_made.return_value = False
        hooks.pgsql_nova_db_joined()
        self.relation_set.assert_called_with(database='nova')

    def test_postgresql_neutron_db_joined(self):
        self.is_relation_made.return_value = False
        hooks.pgsql_neutron_db_joined()
        self.relation_set.assert_called_with(database='neutron')

    def test_db_joined_with_postgresql(self):
        self.is_relation_made.return_value = True

        with self.assertRaises(Exception) as context:
            hooks.db_joined()
        self.assertEqual(context.exception.message,
                         'Attempting to associate a mysql database when'
                         ' there is already associated a postgresql one')

    def test_postgresql_nova_joined_with_db(self):
        self.is_relation_made.return_value = True

        with self.assertRaises(Exception) as context:
            hooks.pgsql_nova_db_joined()
        self.assertEqual(context.exception.message,
                         'Attempting to associate a postgresql database when'
                         ' there is already associated a mysql one')

    def test_postgresql_neutron_joined_with_db(self):
        self.is_relation_made.return_value = True

        with self.assertRaises(Exception) as context:
            hooks.pgsql_neutron_db_joined()
        self.assertEqual(context.exception.message,
                         'Attempting to associate a postgresql database when'
                         ' there is already associated a mysql one')

    @patch.object(hooks, 'CONFIGS')
    def test_db_changed_missing_relation_data(self, configs):
        configs.complete_contexts = MagicMock()
        configs.complete_contexts.return_value = []
        hooks.db_changed()
        self.log.assert_called_with(
            'shared-db relation incomplete. Peer not ready?'
        )

    @patch.object(hooks, 'CONFIGS')
    def test_postgresql_nova_db_changed_missing_relation_data(self, configs):
        configs.complete_contexts = MagicMock()
        configs.complete_contexts.return_value = []
        hooks.postgresql_nova_db_changed()
        self.log.assert_called_with(
            'pgsql-nova-db relation incomplete. Peer not ready?'
        )

    def _shared_db_test(self, configs):
        configs.complete_contexts = MagicMock()
        configs.complete_contexts.return_value = ['shared-db']
        configs.write = MagicMock()
        hooks.db_changed()

    def _postgresql_db_test(self, configs):
        configs.complete_contexts = MagicMock()
        configs.complete_contexts.return_value = ['pgsql-nova-db']
        configs.write = MagicMock()
        hooks.postgresql_nova_db_changed()

    @patch.object(hooks, 'CONFIGS')
    def test_db_changed(self, configs):
        self._shared_db_test(configs)
        self.assertTrue(configs.write_all.called)
        self.migrate_database.assert_called_with()

    @patch.object(hooks, 'CONFIGS')
    def test_db_changed_allowed(self, configs):
        allowed_units = 'nova-cloud-controller/0 nova-cloud-controller/3'
        self.test_relation.set({
            'nova_allowed_units': allowed_units,
        })
        self.local_unit.return_value = 'nova-cloud-controller/3'
        self._shared_db_test(configs)
        self.assertTrue(configs.write_all.called)
        self.migrate_database.assert_called_with()

    @patch.object(hooks, 'CONFIGS')
    def test_db_changed_not_allowed(self, configs):
        allowed_units = 'nova-cloud-controller/0 nova-cloud-controller/3'
        self.test_relation.set({
            'nova_allowed_units': allowed_units,
        })
        self.local_unit.return_value = 'nova-cloud-controller/1'
        self._shared_db_test(configs)
        self.assertTrue(configs.write_all.called)
        self.assertFalse(self.migrate_database.called)

    @patch.object(hooks, 'CONFIGS')
    def test_postgresql_db_changed(self, configs):
        self._postgresql_db_test(configs)
        self.assertTrue(configs.write_all.called)
        self.migrate_database.assert_called_with()

    @patch.object(hooks, 'nova_cell_relation_joined')
    @patch.object(hooks, 'compute_joined')
    @patch.object(hooks, 'CONFIGS')
    def test_db_changed_remote_restarts(self, configs, comp_joined,
                                        cell_joined):
        def _relation_ids(rel):
            relid = {
                'cloud-compute': ['nova-compute/0'],
                'cell': ['nova-cell-api/0'],
            }
            return relid[rel]
        self.relation_ids.side_effect = _relation_ids
        allowed_units = 'nova-cloud-controller/0'
        self.test_relation.set({
            'nova_allowed_units': allowed_units,
        })
        self.local_unit.return_value = 'nova-cloud-controller/0'
        self._shared_db_test(configs)
        comp_joined.assert_called_with(remote_restart=True,
                                       rid='nova-compute/0')
        cell_joined.assert_called_with(remote_restart=True,
                                       rid='nova-cell-api/0')
        self.migrate_database.assert_called_with()

    @patch.object(hooks, 'nova_cell_relation_joined')
    @patch.object(hooks, 'CONFIGS')
    def test_amqp_relation_broken(self, configs, cell_joined):
        configs.write = MagicMock()
        self.relation_ids.return_value = ['nova-cell-api/0']
        hooks.relation_broken()
        self.assertTrue(configs.write_all.called)
        cell_joined.assert_called_with(rid='nova-cell-api/0')

    @patch.object(hooks, 'nova_cell_relation_joined')
    @patch.object(hooks, 'CONFIGS')
    def test_amqp_changed_api_rel(self, configs, cell_joined):
        configs.complete_contexts = MagicMock()
        configs.complete_contexts.return_value = ['amqp']
        configs.write = MagicMock()
        self.is_relation_made.return_value = True
        hooks.amqp_changed()
        self.assertEquals(configs.write.call_args_list,
                          [call('/etc/nova/nova.conf')])

    @patch.object(hooks, 'nova_cell_relation_joined')
    @patch.object(hooks, 'CONFIGS')
    def test_amqp_changed_noapi_rel(self, configs, cell_joined):
        configs.complete_contexts = MagicMock()
        configs.complete_contexts.return_value = ['amqp']
        configs.write = MagicMock()
        self.relation_ids.return_value = ['nova-cell-api/0']
        self.is_relation_made.return_value = False
        self.network_manager.return_value = 'neutron'
        hooks.amqp_changed()
        self.assertEquals(configs.write.call_args_list,
                          [call('/etc/nova/nova.conf'),
                           call('/etc/neutron/neutron.conf')])
        cell_joined.assert_called_with(rid='nova-cell-api/0')

    def test_nova_cell_relation_joined(self):
        self.uuid.uuid4.return_value = 'bob'
        hooks.nova_cell_relation_joined(rid='rid',
                                        remote_restart=True)
        self.relation_set.assert_called_with(restart_trigger='bob',
                                             relation_id='rid')

    @patch.object(hooks, 'CONFIGS')
    def test_nova_cell_relation_changed(self, configs):
        hooks.nova_cell_relation_changed()
        configs.write.assert_called_with('/etc/nova/nova.conf')

    def test_get_cell_type(self):
        self.NovaCellContext().return_value = {
            'cell_type': 'parent',
            'cell_name': 'api',
        }
        self.assertEquals(hooks.get_cell_type(), 'parent')

    @patch.object(os, 'rename')
    @patch.object(os.path, 'isfile')
    @patch.object(hooks, 'CONFIGS')
    @patch.object(hooks, 'get_cell_type')
    def test_neutron_api_relation_joined(self, get_cell_type, configs, isfile,
                                         rename):
        neutron_conf = '/etc/neutron/neutron.conf'
        nova_url = 'http://novaurl:8774/v2'
        isfile.return_value = True
        self.service_running.return_value = True
        _identity_joined = self.patch('identity_joined')
        self.relation_ids.return_value = ['relid']
        self.canonical_url.return_value = 'http://novaurl'
        get_cell_type.return_value = 'parent'
        with patch_open() as (_open, _file):
            hooks.neutron_api_relation_joined()
            self.service_stop.assert_called_with('neutron-server')
            rename.assert_called_with(neutron_conf, neutron_conf + '_unused')
            self.assertTrue(_identity_joined.called)
            self.relation_set.assert_called_with(relation_id=None,
                                                 cell_type='parent',
                                                 nova_url=nova_url)

    @patch.object(hooks, 'CONFIGS')
    def test_neutron_api_relation_changed(self, configs):
        self.relation_ids.return_value = ['relid']
        _compute_joined = self.patch('compute_joined')
        _quantum_joined = self.patch('quantum_joined')
        hooks.neutron_api_relation_changed()
        self.assertTrue(configs.write.called_with('/etc/nova/nova.conf'))
        self.assertTrue(_compute_joined.called)
        self.assertTrue(_quantum_joined.called)

    @patch.object(os, 'remove')
    @patch.object(os.path, 'isfile')
    @patch.object(hooks, 'CONFIGS')
    def test_neutron_api_relation_broken(self, configs, isfile, remove):
        isfile.return_value = True
        self.relation_ids.return_value = ['relid']
        _compute_joined = self.patch('compute_joined')
        _quantum_joined = self.patch('quantum_joined')
        hooks.neutron_api_relation_broken()
        remove.assert_called_with('/etc/init/neutron-server.override')
        self.assertTrue(configs.write_all.called)
        self.assertTrue(_compute_joined.called)
        self.assertTrue(_quantum_joined.called)

    @patch.object(utils, 'config')
    def test_console_settings_vnc(self, _utils_config):
        _utils_config.return_value = 'vnc'
        _cc_host = "nova-cc-host1"
        self.canonical_url.return_value = 'http://' + _cc_host
        _con_sets = hooks.console_settings()
        console_settings = {
            'console_proxy_novnc_address': 'http://%s:6080/vnc_auto.html' %
                                           (_cc_host),
            'console_proxy_novnc_port': 6080,
            'console_access_protocol': 'vnc',
            'console_proxy_novnc_host': _cc_host,
            'console_proxy_xvpvnc_port': 6081,
            'console_proxy_xvpvnc_host': _cc_host,
            'console_proxy_xvpvnc_address': 'http://%s:6081/console' %
                                            (_cc_host),
            'console_keymap': 'en-us'
        }
        self.assertEqual(_con_sets, console_settings)

    @patch.object(utils, 'config')
    def test_console_settings_xvpvnc(self, _utils_config):
        _utils_config.return_value = 'xvpvnc'
        _cc_host = "nova-cc-host1"
        self.canonical_url.return_value = 'http://' + _cc_host
        _con_sets = hooks.console_settings()
        console_settings = {
            'console_access_protocol': 'xvpvnc',
            'console_keymap': 'en-us',
            'console_proxy_xvpvnc_port': 6081,
            'console_proxy_xvpvnc_host': _cc_host,
            'console_proxy_xvpvnc_address': 'http://%s:6081/console' %
                                            (_cc_host),
        }
        self.assertEqual(_con_sets, console_settings)

    @patch.object(utils, 'config')
    def test_console_settings_novnc(self, _utils_config):
        _utils_config.return_value = 'novnc'
        _cc_host = "nova-cc-host1"
        self.canonical_url.return_value = 'http://' + _cc_host
        _con_sets = hooks.console_settings()
        console_settings = {
            'console_proxy_novnc_address': 'http://%s:6080/vnc_auto.html' %
                                           (_cc_host),
            'console_proxy_novnc_port': 6080,
            'console_access_protocol': 'novnc',
            'console_proxy_novnc_host': _cc_host,
            'console_keymap': 'en-us'
        }
        self.assertEqual(_con_sets, console_settings)

    @patch.object(utils, 'config')
    def test_console_settings_spice(self, _utils_config):
        _utils_config.return_value = 'spice'
        _cc_host = "nova-cc-host1"
        self.canonical_url.return_value = 'http://' + _cc_host
        _con_sets = hooks.console_settings()
        console_settings = {
            'console_proxy_spice_address': 'http://%s:6082/spice_auto.html' %
                                           (_cc_host),
            'console_proxy_spice_host': _cc_host,
            'console_proxy_spice_port': 6082,
            'console_access_protocol': 'spice',
            'console_keymap': 'en-us'
        }
        self.assertEqual(_con_sets, console_settings)

    @patch.object(utils, 'config')
    def test_console_settings_explicit_ip(self, _utils_config):
        _utils_config.return_value = 'spice'
        _cc_public_host = "public-host"
        _cc_private_host = "private-host"
        self.test_config.set('console-proxy-ip', _cc_public_host)
        _con_sets = hooks.console_settings()
        self.canonical_url.return_value = 'http://' + _cc_private_host
        console_settings = {
            'console_proxy_spice_address': 'http://%s:6082/spice_auto.html' %
                                           (_cc_public_host),
            'console_proxy_spice_host': _cc_public_host,
            'console_proxy_spice_port': 6082,
            'console_access_protocol': 'spice',
            'console_keymap': 'en-us'
        }
        self.assertEqual(_con_sets, console_settings)
