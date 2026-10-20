#!/usr/bin/env python3
"""Check new release/provenance boundaries using isolated source fixtures."""
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
SCRIPT=ROOT/'.github/scripts/verify-ax6-source-semantics.sh'
PACKAGES={
    'SOURCE_MAC80211_PKG_RELEASE':'package/kernel/mac80211',
    'SOURCE_HOSTAPD_PKG_RELEASE':'package/network/services/hostapd',
    'SOURCE_QCA_NSS_DP_PKG_RELEASE':'package/qca-nss/qca-nss-dp',
    'SOURCE_QCA_NSS_DRV_PKG_RELEASE':'package/qca-nss/qca-nss-drv',
    'SOURCE_QCA_NSS_ECM_PKG_RELEASE':'package/qca-nss/qca-nss-ecm',
    'SOURCE_QCA_NSS_CLIENTS_PKG_RELEASE':'package/qca-nss/qca-nss-clients',
    'SOURCE_QCA_MCS_PKG_RELEASE':'package/qca-nss/qca-mcs',
    'SOURCE_QCA_NSS_SSDK_PKG_RELEASE':'package/qca-nss/qca-ssdk',
    'SOURCE_RPCD_PKG_RELEASE':'package/system/rpcd'}


class Semantics(unittest.TestCase):
    def test_workflow_exports_new_release_fields(self):
        text=(ROOT/'.github/workflows/build-AX6-NSS.yml').read_text()
        start=text.index('          for name in',text.index('- name: Load and verify build lock'))
        end=text.index('\n          done',start)+len('\n          done')
        loop='\n'.join(line[10:] for line in text[start:end].splitlines())
        names=re.findall(r'\b[A-Z][A-Z0-9_]+\b',loop.split('; do')[0])
        for name in ('SOURCE_QCA_NSS_SSDK_PKG_RELEASE','SOURCE_RPCD_PKG_RELEASE'):
            self.assertIn(name,names)
        with tempfile.TemporaryDirectory() as tmp:
            env=dict(os.environ,**{name:'1' for name in names})
            target=Path(tmp)/'exported.env'
            env.update(GITHUB_ENV=str(target),BUILD_LOCK='fixture.env')
            p=subprocess.run(['bash','-c',loop],env=env,capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stderr)
            fields=dict(line.split('=',1) for line in target.read_text().splitlines())
            for name in ('SOURCE_QCA_NSS_SSDK_PKG_RELEASE','SOURCE_RPCD_PKG_RELEASE'):
                self.assertEqual(fields[name],'1')
                missing=env.copy();missing.pop(name)
                p=subprocess.run(['bash','-c',loop],env=missing,capture_output=True,text=True)
                self.assertNotEqual(p.returncode,0)
                self.assertIn(name+' is missing',p.stdout)

    def fixture(self,edit=None):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            lock=root/'lock.env'
            lock.write_text(''.join(k+'=1\n' for k in PACKAGES))
            for path in PACKAGES.values():
                p=root/path/'Makefile';p.parent.mkdir(parents=True,exist_ok=True)
                p.write_text('PKG_RELEASE:=1\n')
            provenance=root/'package/system/rpcd/provenance.json'
            provenance.write_text(json.dumps({'package_release':1,'default_checked_support':False}))
            stride=root/'package/kernel/mac80211/patches/ath11k/102-wifi-ath11k-fix-stride-mismatch-in-mac_phy_caps_parse.patch'
            stride.parent.mkdir(parents=True)
            stride.write_text('From 7a246c72132eb943b5844ba79dad597b47429dba \n'
                '+ kcalloc(svc_rdy_ext->tot_phy_id,\n+ sizeof(*svc_rdy_ext->mac_phy_caps), GFP_ATOMIC)\n')
            if edit:edit(root,lock,provenance)
            p=subprocess.run(['sh',str(SCRIPT),str(root),str(lock)],capture_output=True,text=True)
            return p.returncode,p.stdout+p.stderr

    def test_complete_consistent_fixture(self):
        self.assertEqual(self.fixture()[0],0)

    def test_rpcd_release_drift(self):
        code,text=self.fixture(lambda r,l,p:(r/'package/system/rpcd/Makefile').write_text('PKG_RELEASE:=2\n'))
        self.assertNotEqual(code,0);self.assertIn('rpcd mismatch',text)

    def test_ssdk_release_drift(self):
        code,text=self.fixture(lambda r,l,p:(r/'package/qca-nss/qca-ssdk/Makefile').write_text('PKG_RELEASE:=2\n'))
        self.assertNotEqual(code,0);self.assertIn('qca-ssdk mismatch',text)

    def test_provenance_release_drift(self):
        self.assertNotEqual(self.fixture(lambda r,l,p:p.write_text(json.dumps({'package_release':2,'default_checked_support':False})))[0],0)

    def test_provenance_boolean_not_numeric_release(self):
        self.assertNotEqual(self.fixture(lambda r,l,p:p.write_text(json.dumps({'package_release':True,'default_checked_support':False})))[0],0)

    def test_experimental_on_rejected(self):
        self.assertNotEqual(self.fixture(lambda r,l,p:p.write_text(json.dumps({'package_release':1,'default_checked_support':True})))[0],0)

    def test_missing_or_malformed_provenance(self):
        for content in ('bad json','[]','null'):
            self.assertNotEqual(self.fixture(lambda r,l,p:p.write_text(content))[0],0)
        self.assertNotEqual(self.fixture(lambda r,l,p:p.unlink())[0],0)

    def test_duplicate_lock_key_even_if_values_match(self):
        code,text=self.fixture(lambda r,l,p:l.write_text(l.read_text()+'SOURCE_RPCD_PKG_RELEASE=1\n'))
        self.assertNotEqual(code,0);self.assertIn('exactly once',text)

    def test_duplicate_provenance_field_even_if_values_match(self):
        content='{"package_release":1,"package_release":1,"default_checked_support":false}'
        code,text=self.fixture(lambda r,l,p:p.write_text(content))
        self.assertNotEqual(code,0);self.assertIn('duplicate JSON field',text)

    def test_missing_release_key(self):
        self.assertNotEqual(self.fixture(lambda r,l,p:l.write_text(l.read_text().replace('SOURCE_RPCD_PKG_RELEASE=1\n','')))[0],0)

    def test_duplicate_source_release(self):
        self.assertNotEqual(self.fixture(lambda r,l,p:(r/'package/system/rpcd/Makefile').write_text('PKG_RELEASE:=1\nPKG_RELEASE:=1\n'))[0],0)


if __name__=='__main__':
    unittest.main()
