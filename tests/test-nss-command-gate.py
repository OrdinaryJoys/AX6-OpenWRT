#!/usr/bin/env python3
"""Synthetic BUILD-gate controls only; no NSS C or saved native artifact runs."""
import copy
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('nss_command_gate',
    ROOT / '.github/scripts/verify-nss-command-inputs.py')
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


class Admission(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.source = self.root / 'source'
        self.trees = {name: self.root / name for name in gate.PACKAGES}
        self.contract = {'schema': 1, 'profile': 'NSS_COMMAND_INPUTS_DRV25_CLIENTS29',
                         'frozen': True, 'assets': {}, 'recipes': {},
                         'runner': 'tests/test-nss-command-inputs.py'}
        self.prepared = {'schema': 1, 'metadata_rule_inputs': {}}
        for label, (package, release) in gate.PACKAGES.items():
            pin = ('a' if label == 'driver' else 'b') * 40
            recipe = f'PKG_RELEASE:={release}\nPKG_SOURCE_VERSION:={pin[:12]}\n'
            self.write(self.source, 'package/qca-nss/' + package + '/Makefile', recipe)
            self.contract['recipes'][label] = gate.sha(recipe.encode())
            self.write(self.source, 'package/qca-nss/' + package + '/patches/001.patch', 'TESTONLY patch')
            self.write(self.trees[label], 'actual.c', 'TESTONLY tree, never compiled')
            digest = gate.inventory_hash(gate.inventory(self.trees[label]))
            self.prepared[label] = {'package': package, 'pin': pin, 'files': 1,
                'candidate_inventory_sha256': digest, 'baseline_inventory_sha256': digest,
                'patches': {'001.patch': gate.sha(b'TESTONLY patch')}}
        for name in (self.contract['runner'], 'tests/nss-command-inputs/source.py',
                     'include/package-defaults.mk', 'include/package.mk'):
            self.write(self.source, name, 'TESTONLY data; never executed')
            self.contract['assets'][name] = gate.sha(b'TESTONLY data; never executed')
            if name.startswith('include/'):
                self.prepared['metadata_rule_inputs'][name] = self.contract['assets'][name]
        self.save_profile()

    def write(self, root, name, text):
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        return p

    def save_profile(self):
        name = 'tests/nss-command-inputs/profile.json'
        p = self.write(self.source, name, json.dumps(self.prepared))
        self.contract['source_profile'] = {'path': name, 'sha256': gate.sha(p.read_bytes())}

    def admit(self):
        return gate.admit(self.source, self.trees['driver'], self.trees['clients'], self.contract)

    def reject(self, reason):
        with self.assertRaisesRegex(ValueError, reason):
            self.admit()

    def test_positive_is_text_admission_only(self):
        self.assertEqual(self.admit()['profile'], self.prepared)

    def test_tree_change_add_remove(self):
        for mutation in ('change', 'add', 'remove'):
            with self.subTest(mutation=mutation):
                tree = self.trees['driver']
                (tree / 'actual.c').write_text('TESTONLY tree, never compiled')
                if mutation == 'change': (tree / 'actual.c').write_text('drift')
                elif mutation == 'add': (tree / 'foreign.c').write_text('extra')
                else: (tree / 'actual.c').unlink()
                self.reject('whole prepared tree drift')
                (tree / 'foreign.c').unlink(missing_ok=True)

    def test_source_profile_cannot_refresh_from_actual_tree(self):
        self.prepared['driver']['candidate_inventory_sha256'] = gate.sha(b'new')
        p = self.source / self.contract['source_profile']['path']
        p.write_text(json.dumps(self.prepared))
        self.reject('input hash drift')

    def test_recipe_hash_including_release_is_exact(self):
        package = self.source / 'package/qca-nss/qca-nss-drv'
        (package / 'Makefile').write_text('PKG_RELEASE:=26\n')
        self.reject('recipe hash drift')

    def test_wrong_release_rejected_even_if_test_profile_rehashed(self):
        p = self.source / 'package/qca-nss/qca-nss-clients/Makefile'
        p.write_text(p.read_text().replace('29', '30'))
        self.contract['recipes']['clients'] = gate.sha(p.read_bytes())
        self.reject('recipe release')

    def test_clients28_recipe_cannot_be_relabelled_as29(self):
        p=self.source/'package/qca-nss/qca-nss-clients/Makefile'
        p.write_text(p.read_text().replace('29','28'))
        self.contract['recipes']['clients']=gate.sha(p.read_bytes())
        self.reject('recipe release')

    def test_patch_change_or_add(self):
        patches = self.source / 'package/qca-nss/qca-nss-drv/patches'
        (patches / '001.patch').write_text('changed')
        self.reject('complete patch inventory drift')
        (patches / '001.patch').write_text('TESTONLY patch')
        (patches / '002.patch').write_text('added')
        self.reject('complete patch inventory drift')

    def test_added_support_file_is_not_ignored(self):
        self.write(self.source, 'tests/nss-command-inputs/foreign.py', 'extra')
        self.reject('support inventory drift')

    def test_asset_drift(self):
        (self.source / self.contract['runner']).write_text('changed')
        self.reject('input hash drift')

    def test_symlink_in_prepared_tree(self):
        (self.trees['driver'] / 'link').symlink_to(self.trees['driver'] / 'actual.c')
        self.reject('symlink inventory')

    def test_unfrozen_profile(self):
        self.contract['frozen'] = False
        self.reject('unfrozen or unknown')

    def test_boolean_schema(self):
        self.contract['schema'] = True
        self.reject('unfrozen or unknown')

    def test_duplicate_json_key(self):
        with self.assertRaisesRegex(ValueError, 'duplicate JSON key'):
            json.loads('{"status":1,"status":2}', object_pairs_hook=gate.unique)


class RawReceipt(Admission):
    """Synthetic data in the actual receipt schema; no native program executes."""
    def setUp(self):
        super().setUp()
        self.state = self.admit()
        self.directory = self.root / 'suite'
        self.directory.mkdir()
        self.cc = 'TESTONLY-cc'
        self.data = self.make_receipt(self.directory)

    def put(self, root, name, raw):
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(raw if isinstance(raw, bytes) else raw.encode())

    def make_receipt(self, root):
        rows = []
        data = dict(status='PASS_HOST_COMMAND_INPUTS_ONLY',
            qualification='HOST_MODELS_NOT_TARGET_ABI_FW_OR_LIFETIME', sanitize=True,
            LSan='NOT_VERIFIED', end_input_stability=True, positive_count=20, negative_count=22,
            positives=list(gate.CASES), negatives=[list(r) for r in gate.NEGATIVES],
            inventory_controls=dict(valid=1,rejected=6,classification='PYTHON_INVENTORY_CONTROLS_NOT_SOURCE_MUTANTS'),
            metadata_controls=dict(valid=1,rejected=7,classification='METADATA_MODEL_CONTROLS_NOT_SOURCE_MUTANTS'),
            numeric_model_controls=dict(valid=1,rejected=1,
                classification='NATIVE_NUMERIC_MODEL_CONTROL_NOT_PRODUCTION_SOURCE_MUTANT',
                mutation='Remove only libc EOF-to-kernel zero-assignment normalization',marker='KERNEL_SCAN_EMPTY'),
            source_profile_sha256=self.contract['source_profile']['sha256'],
            inputs=self.state['inputs'], prepared_metadata=self.state['metadata'], commands=rows,
            fixed_source_contract={k:{n:v for n,v in self.prepared[k].items() if n!='patches'} for k in gate.PACKAGES})
        for name, value in [('INPUTS.json', data['inputs']), ('TREES.json', self.state['trees']),
                            ('OBLIGATIONS.json', data['negatives'])]:
            self.put(root, name, json.dumps(value))
        for name, raw in [('input.c', b'TESTONLY metadata admission data, never compiled\n'),
                          ('version.date', b'1770000000\n'), ('.prepared_'+'a'*32+'_'+'b'*32,b'')]:
            self.put(root, 'metadata-controls/'+name, raw)
        def record(stem, command, rc=0, out=b'', err=b'', code=None):
            row = dict(label=stem,command=command,returncode=rc,timeout=False,
                ASAN_OPTIONS='detect_leaks=0:abort_on_error=0:exitcode='+str(code or 97),
                UBSAN_OPTIONS='halt_on_error=1:exitcode='+str(code or 98)+':print_stacktrace=1')
            for stream, raw in [('stdout',out),('stderr',err)]:
                row[stream+'_file']=stem+'.'+stream
                row[stream+'_sha256']=gate.sha(raw)
                self.put(root, stem+'.'+stream, raw)
            self.put(root, stem+'.json', json.dumps(row))
            rows.append(row)
        def compile_program(label, canary=False):
            names=['fixture.c'] if canary else ['fixture.c','types.h','model.h',*('actual-'+g+'.c' for g in ('scan','ppe','mirror','tunip'))]
            for name in names:
                raw=b'TESTONLY whole C/type data'
                if name=='model.h':
                    raw+=b' return result;' if label=='numeric-model/libc-eof' else b' return result==EOF?0:result;'
                self.put(root,label+'/'+name,raw)
            self.put(root,label+'/program.host',b'TESTONLY non-executable bytes')
            record(label+'/compile',[self.cc,*gate.FLAGS,str(root/label/'fixture.c'),'-o',str(root/label/'program.host')])
        for label in gate.PACKAGES:
            for prefix in ('baseline-','roundtrip-'):
                self.put(root,prefix+label+'/actual.c',b'TESTONLY tree, never compiled')
            for direction in ('reverse','forward'):
                record(label+'-'+direction,['/TESTONLY/patch','--batch','--fuzz=0','-p1']+(['-R'] if direction=='reverse' else []))
        compile_program('positive')
        raw=b'PASS kernel-numeric-model\n'
        self.put(root,'numeric-model/positive.expected',raw)
        record('numeric-model/positive',[str(root/'positive/program.host'),'kernel-numeric-model'],out=raw)
        compile_program('numeric-model/libc-eof')
        raw=b'NSS_INPUT:KERNEL_SCAN_EMPTY\n'
        self.put(root,'numeric-model/negative.expected',raw)
        record('numeric-model/negative',[str(root/'numeric-model/libc-eof/program.host'),'kernel-numeric-model'],86,err=raw)
        for case in gate.CASES:
            raw=('PASS '+case+'\n').encode()
            self.put(root,'positive/'+case+'.expected',raw)
            record('positive/'+case,[str(root/'positive/program.host'),case],out=raw)
        for name,case,marker in gate.NEGATIVES:
            label='negative/'+name
            compile_program(label)
            raw=('NSS_INPUT:'+marker+'\n').encode()
            self.put(root,label+'/stderr.expected',raw)
            record(label+'/run',[str(root/label/'program.host'),case],86,err=raw)
        data['sanitizer_controls']=[]
        for name,code,raw in [('asan',97,b'ERROR: AddressSanitizer: heap-buffer-overflow\nWRITE of size 4\n'),
                              ('ubsan',98,b'runtime error: signed integer overflow: 2147483647 + 1\n')]:
            label='canary/'+name
            compile_program(label,True)
            record(label+'/run',[str(root/label/'program.host')],code,err=raw,code=code)
            row=rows[-1]
            data['sanitizer_controls'].append(dict(name=name,exitcode=code,
                diagnostic='ERROR: AddressSanitizer: heap-buffer-overflow' if code==97 else 'runtime error: signed integer overflow:',
                ASAN_OPTIONS=row['ASAN_OPTIONS'],UBSAN_OPTIONS=row['UBSAN_OPTIONS']))
        data['generated']=gate.inventory(root)
        return data

    def verify(self):
        return gate.verify_receipt(self.directory,self.data,self.state,self.contract,self.cc)

    def reject_receipt(self, reason):
        with self.assertRaisesRegex(ValueError, reason): self.verify()

    def refresh(self,index,**changes):
        row=self.data['commands'][index]
        row.update(changes)
        self.put(self.directory,row['label']+'.json',json.dumps(row))
        self.data['generated']=gate.inventory(self.directory)

    def command_index(self,label):
        return next(i for i,row in enumerate(self.data['commands']) if row['label']==label)

    def test_exact_actual_receipt(self):
        detail=self.verify()
        self.assertEqual((detail['commands'],detail['source_and_regular_commands'],detail['numeric_model_commands']),(76,73,3))

    def test_missing_duplicate_inventories(self):
        for field in ('positives','negatives','commands'):
            original=copy.deepcopy(self.data[field])
            self.data[field][-1]=self.data[field][0]
            self.reject_receipt('complete .*inventory')
            self.data[field]=original

    def test_semantic_negative_exact86(self):
        index=self.command_index('negative/sequence-short/run')
        row=copy.deepcopy(self.data['commands'][index])
        for changes in ({'returncode':0},{'returncode':-11},{'returncode':97},
                        {'returncode':98},{'returncode':True},{'timeout':True}):
            self.data['commands'][index]=copy.deepcopy(row)
            self.refresh(index,**changes)
            self.reject_receipt('process exit/timeout')

    def test_compile_failure_not_negative_credit(self):
        self.refresh(self.command_index('negative/sequence-short/compile'),returncode=1)
        self.reject_receipt('process exit/timeout')

    def test_rehashed_negative_noise(self):
        index=self.command_index('negative/sequence-short/run')
        for stream,raw in [('stdout',b'noise'),('stderr',b'NSS_INPUT:SEQ_RANGE\nAddressSanitizer: crash\n')]:
            row=self.data['commands'][index]
            self.put(self.directory,row['label']+'.'+stream,raw)
            self.refresh(index,**{stream+'_sha256':gate.sha(raw)})
            self.reject_receipt('exact raw')
            self.put(self.directory,row['label']+'.'+stream,b'' if stream=='stdout' else b'NSS_INPUT:SEQ_RANGE\n')
            self.refresh(index,**{stream+'_sha256':gate.sha(b'' if stream=='stdout' else b'NSS_INPUT:SEQ_RANGE\n')})

    def test_whole_c_and_binary_drift(self):
        for name in ('negative/sequence-short/actual-scan.c','positive/program.host'):
            p=self.directory/name; original=p.read_bytes(); p.write_bytes(b'changed')
            self.reject_receipt('whole C/binary/log/generated')
            p.write_bytes(original)

    def test_extra_output_even_rehashed(self):
        self.put(self.directory,'extra.host',b'extra')
        self.data['generated']=gate.inventory(self.directory)
        self.reject_receipt('whole C/binary/log/generated')

    def test_expected_not_refreshed_from_file(self):
        self.put(self.directory,'positive/sequence-bounds.expected',b'PASS wrong\n')
        self.data['generated']=gate.inventory(self.directory)
        self.reject_receipt('positive expected bytes')

    def test_canary_common_exitcode(self):
        index=next(i for i,row in enumerate(self.data['commands']) if row['label']=='canary/asan/run')
        self.refresh(index,UBSAN_OPTIONS='halt_on_error=1:exitcode=98')
        self.reject_receipt('canary common exitcode')

    def test_prior19_inventory_is_not_current_qualification(self):
        self.data['negative_count']=19
        self.data['negatives']=[r for r in self.data['negatives'] if r[0]!='mirror-empty-name']
        self.reject_receipt('complete negative inventory')

    def test_prior20_inventory_is_not_current_qualification(self):
        self.data['negative_count']=20
        self.data['negatives']=[r for r in self.data['negatives'] if r[0] not in ('mirror-display-empty','mirror-next-empty')]
        self.reject_receipt('complete negative inventory')

    def test_new_guard_case_and_marker_are_fixed_independently(self):
        index=next(i for i,row in enumerate(self.data['negatives']) if row[0]=='mirror-empty-name')
        for replacement in (['mirror-empty-name','mirror-errors','MIRROR_EMPTY_NAME'],
                            ['mirror-empty-name','mirror-invalid','MIRROR_INVALID']):
            self.data['negatives'][index]=replacement
            self.reject_receipt('complete negative inventory')

    def test_new_guard_requires_exact86_runtime_rejection(self):
        for name in ('mirror-empty-name','mirror-display-empty','mirror-next-empty'):
            label='negative/'+name+'/run'
            index=self.command_index(label)
            self.refresh(index,returncode=0)
            self.reject_receipt('process exit/timeout: '+label)
            self.refresh(index,returncode=86)

    def test_old69_commands_cannot_omit_new_guards_and_model_controls(self):
        self.data['commands']=[r for r in self.data['commands'] if not
            r['label'].startswith(('negative/mirror-display-empty/','negative/mirror-next-empty/','numeric-model/'))]
        self.assertEqual(len(self.data['commands']),69)
        self.reject_receipt('complete command inventory')

    def test_model_controls_cannot_be_reclassified_as_source_mutants(self):
        self.data['numeric_model_controls']['classification']='PRODUCTION_SOURCE_MUTANT'
        self.reject_receipt('independent numeric model classification')

    def test_model_reverse_control_requires_exact86(self):
        self.refresh(self.command_index('numeric-model/negative'),returncode=98)
        self.reject_receipt('process exit/timeout: numeric-model/negative')

    def test_model_control_cannot_change_production_c_even_if_rehashed(self):
        self.put(self.directory,'numeric-model/libc-eof/actual-tunip.c',b'changed')
        self.data['generated']=gate.inventory(self.directory)
        self.reject_receipt('numeric control must not mutate production C')

    def test_model_control_delta_is_exact(self):
        self.put(self.directory,'numeric-model/libc-eof/model.h',b'changed')
        self.data['generated']=gate.inventory(self.directory)
        self.reject_receipt('restricted numeric model-only delta')

    def test_development_not_final(self):
        self.data['status']='DEV_ONLY'
        self.reject_receipt('host-only qualification')

    def test_archived_tree_drift(self):
        self.put(self.directory,'baseline-driver/actual.c',b'changed')
        self.data['generated']=gate.inventory(self.directory)
        self.reject_receipt('archived whole tree')

    def test_metadata_exact_classes(self):
        tree=self.trees['driver']; stamp='.prepared_'+'a'*32+'_'+'b'*32
        self.put(tree,'version.date',b'1770000000\n'); self.put(tree,stamp,b'')
        self.assertEqual(set(self.admit()['metadata'][str(tree)]),{'version.date',stamp})
        for name in ('.configured','rogue.c','nested/version.date','.prepared_wrong'):
            self.put(tree,name,b''); self.reject('whole prepared tree drift'); (tree/name).unlink()
        self.put(tree,stamp,b'wrong'); self.reject('prepared stamp content/duplicate')
        self.put(tree,stamp,b''); self.put(tree,'.prepared_'+'c'*32+'_'+'d'*32,b'')
        self.reject('prepared stamp content/duplicate')

    def test_version_date_invalid_content_rejected(self):
        tree=self.trees['driver']
        for raw in (b'',b'-1\n',b'123',b'123\nextra\n',b'1'*20+b'\n'):
            self.put(tree,'version.date',raw)
            self.reject('version.date content')

    def test_dsym_not_arbitrary_ignore(self):
        self.put(self.directory,'positive/program.host.dSYM/arbitrary',b'extra')
        self.data['generated']=gate.inventory(self.directory)
        self.reject_receipt('dSYM exact shape')


class Invocation(RawReceipt):
    """Mock only source-process handoff, never NSS qualification."""
    def exercise(self,callback=None):
        profile=self.root/'BUILD-contract.json'; profile.write_text(json.dumps(self.contract))
        output=self.root/'out'
        def process(command,**kwargs):
            self.assertEqual(command[1:3],['-B','-O']); self.assertIn('--sanitize',command)
            self.assertEqual(Path(command[3]),self.source/self.contract['runner'])
            self.assertEqual(command[command.index('--driver')+1],str(self.trees['driver']))
            self.assertEqual(command[command.index('--clients')+1],str(self.trees['clients']))
            self.directory=output/'suite'; self.directory.mkdir()
            data=self.make_receipt(self.directory)
            self.put(self.directory,'RESULTS.json',json.dumps(data))
            if callback: callback(profile)
            summary=json.dumps(dict(status='PASS_HOST_COMMAND_INPUTS_ONLY',positive_count=20,negative_count=22)).encode()+b'\n'
            return gate.subprocess.CompletedProcess(command,0,summary,b'')
        args=['gate','--source-root',str(self.source),'--driver',str(self.trees['driver']),
              '--clients',str(self.trees['clients']),'--cc',self.cc,'--output',str(output)]
        with patch.object(gate,'PROFILE',profile),patch.object(gate.sys,'argv',args), \
             patch.object(gate.subprocess,'run',process),contextlib.redirect_stdout(io.StringIO()):
            status=gate.main()
        return status,json.loads((output/'RESULTS.json').read_text())

    def test_real_cli_shape_and_adapter(self):
        status,report=self.exercise(); self.assertEqual(status,0); self.assertFalse(report['runtime_approved'])

    def test_end_added_patch(self):
        def corrupt(_): self.write(self.source,'package/qca-nss/qca-nss-drv/patches/999.patch','extra')
        status,report=self.exercise(corrupt); self.assertEqual(status,1)
        self.assertIn('complete patch inventory drift',report['error'])

    def test_end_metadata_change(self):
        def corrupt(_): self.write(self.trees['clients'],'version.date','1770000000\n')
        status,report=self.exercise(corrupt); self.assertEqual(status,1)
        self.assertIn('end input/tree/metadata drift',report['error'])

    def test_end_build_profile_change(self):
        def corrupt(p): p.write_bytes(p.read_bytes()+b'\n')
        status,report=self.exercise(corrupt); self.assertEqual(status,1)
        self.assertIn('BUILD gate/profile changed',report['error'])


class UploadControl(unittest.TestCase):
    """Simulate default hidden-file omission using inert, non-executable data."""
    def setUp(self):
        self.fixture=RawReceipt('test_exact_actual_receipt')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root=self.fixture.root
        self.put=self.fixture.put
        self.put(self.root,'suite/RESULTS.json',json.dumps(self.fixture.data))
        self.digest=gate.sha((self.root/'suite/RESULTS.json').read_bytes())

    def export(self):
        record=gate.export_upload_control(self.root,self.digest)
        self.report=dict(status='PASS_FROZEN_HOST_COMMAND_INPUTS_NOT_RUNTIME',runtime_approved=False,
                         source_receipt_sha256=self.digest,upload_control_export=record)
        self.put(self.root,'RESULTS.json',json.dumps(self.report))
        return record

    def omit_hidden(self):
        (self.root/gate.CONTROL_PATH).unlink()

    def reject_readback(self,reason):
        with self.assertRaisesRegex(ValueError,reason): gate.restore_upload_control(self.root)

    def test_exact_export_does_not_change_suite(self):
        before=gate.inventory(self.root/'suite')
        record=self.export()
        self.assertEqual(gate.inventory(self.root/'suite'),before)
        self.assertEqual((self.root/gate.UPLOAD_DATA).read_bytes(),b'')
        self.assertEqual(record['data_sha256'],'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855')
        self.assertEqual(set(gate.inventory(self.root/gate.UPLOAD_DIRECTORY)),
                         {'INDEX.json','prepared-control-empty.dat'})
        self.assertEqual(gate.read_json(self.root/gate.UPLOAD_INDEX),gate.upload_index(self.digest))

    def test_default_upload_omission_restore_then_full_receipt_verification(self):
        self.export(); self.omit_hidden()
        restored=gate.restore_upload_control(self.root)
        self.assertTrue(restored['restored'])
        self.assertEqual(self.fixture.verify()['commands'],76)
        self.assertFalse(gate.restore_upload_control(self.root)['restored'])

    def test_readback_cli_never_executes_programs(self):
        self.export(); self.omit_hidden()
        args=['gate','--restore-upload-control',str(self.root)]
        with patch.object(gate.sys,'argv',args),patch.object(gate.subprocess,'run',
                side_effect=AssertionError('readback must not execute')) as run,contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(gate.main(),0)
        run.assert_not_called()

    def test_extra_hidden_file_or_empty_directory_rejected(self):
        for name,directory in [('.extra',False),('.empty',True),('suite/metadata-controls/.prepared_wrong',False)]:
            p=self.root/name
            if directory: p.mkdir()
            else: self.put(self.root,name,b'')
            with self.assertRaisesRegex(ValueError,'unexpected hidden export entry'):
                gate.export_upload_control(self.root,self.digest)
            if directory: p.rmdir()
            else: p.unlink()

    def test_nonempty_original_is_not_exported(self):
        self.put(self.root,gate.CONTROL_PATH,b'not empty')
        with self.assertRaisesRegex(ValueError,'export original control content'):
            gate.export_upload_control(self.root,self.digest)

    def test_nonempty_dat_is_not_restored(self):
        self.export(); self.omit_hidden(); self.put(self.root,gate.UPLOAD_DATA,b'not empty')
        self.reject_readback('upload empty data content')
        self.assertFalse((self.root/gate.CONTROL_PATH).exists())

    def test_missing_dat_is_not_synthesized(self):
        self.export(); self.omit_hidden(); (self.root/gate.UPLOAD_DATA).unlink()
        self.reject_readback('missing regular input')
        self.assertFalse((self.root/gate.CONTROL_PATH).exists())

    def test_dat_index_and_original_symlinks_rejected(self):
        self.export()
        for name in (gate.UPLOAD_DATA,gate.UPLOAD_INDEX,gate.CONTROL_PATH):
            p=self.root/name; saved=self.root/'saved-data'; p.rename(saved); p.symlink_to(saved)
            self.reject_readback('symlink inventory')
            p.unlink(); saved.rename(p)

    def test_control_parent_and_export_directory_symlinks_rejected(self):
        self.export()
        for name in ('suite/metadata-controls',gate.UPLOAD_DIRECTORY):
            p=self.root/name; saved=self.root/'saved-directory'; p.rename(saved); p.symlink_to(saved,target_is_directory=True)
            self.reject_readback('symlink inventory')
            p.unlink(); saved.rename(p)

    def test_index_cannot_select_other_paths_or_entries(self):
        self.export(); self.omit_hidden()
        original=gate.upload_index(self.digest)
        for change in ('original','export','extra','size','schema'):
            index=copy.deepcopy(original)
            if change=='original': index['files'][0]['original_path']='suite/other'
            elif change=='export': index['files'][0]['export_path']='other.dat'
            elif change=='extra': index['files'].append(copy.deepcopy(index['files'][0]))
            elif change=='size': index['files'][0]['size']=False
            else: index['schema']=True
            self.put(self.root,gate.UPLOAD_INDEX,json.dumps(index))
            self.reject_readback('upload fixed INDEX contract')
        self.assertFalse((self.root/gate.CONTROL_PATH).exists())

    def test_export_inventory_rejects_additional_nonhidden_data(self):
        self.export(); self.omit_hidden(); self.put(self.root,gate.UPLOAD_DIRECTORY+'/extra.dat',b'')
        self.reject_readback('upload exact export inventory')

    def test_source_receipt_and_wrapper_export_hashes_are_bound(self):
        self.export(); self.omit_hidden()
        source=self.root/'suite/RESULTS.json'; original=source.read_bytes(); source.write_bytes(original+b'\n')
        self.reject_readback('upload source receipt binding'); source.write_bytes(original)
        self.report['upload_control_export']['index_sha256']='0'*64
        self.put(self.root,'RESULTS.json',json.dumps(self.report))
        self.reject_readback('upload wrapper export binding')

    def test_extra_hidden_receipt_key_is_not_a_new_allowance(self):
        self.fixture.data['generated']['other/.hidden']=gate.EMPTY_SHA256
        self.put(self.root,'suite/RESULTS.json',json.dumps(self.fixture.data))
        self.digest=gate.sha((self.root/'suite/RESULTS.json').read_bytes())
        with self.assertRaisesRegex(ValueError,'upload fixed hidden generated inventory'): self.export()

    def test_duplicate_index_keys_rejected(self):
        self.export(); self.omit_hidden()
        self.put(self.root,gate.UPLOAD_INDEX,'{"schema":1,"schema":1}')
        self.reject_readback('duplicate JSON key')


class Wiring(unittest.TestCase):
    def step(self):
        workflow=(ROOT/'.github/workflows/build-AX6-NSS.yml').read_text()
        marker='      - name: Validate frozen NSS command input source and host regressions\n'
        self.assertEqual(workflow.count(marker),1)
        step=workflow.split(marker,1)[1].split('\n      - ',1)[0]
        script='\n'.join(line[10:] for line in step.split('        run: |\n',1)[1].splitlines())+'\n'
        return workflow,script

    def test_order_unique_and_lint(self):
        workflow,script=self.step()
        call='python3 "$GITHUB_WORKSPACE/.github/scripts/verify-nss-command-inputs.py"'
        self.assertEqual(workflow.count(call),1)
        root_call='python3 "$GITHUB_WORKSPACE/.github/scripts/verify-nss-root-host.py"'
        self.assertEqual(workflow.count(root_call),1)
        self.assertLess(script.index(root_call),script.index(call))
        self.assertIn('--source-root . --driver "${command_drivers[0]}"',script)
        self.assertIn('--driver "$evidence/root-host/driver25-prefix"',script)
        for text in ('--source-root "$GITHUB_WORKSPACE/core-accepted-source" --driver ',
                     'command_drivers[0]','command_clients[0]','--output "$evidence/validation"'):
            self.assertIn(text,script)
        self.assertLess(workflow.index('Validate reviewed MDIO lifecycle source and host regressions'),workflow.index(call))
        self.assertLess(workflow.index(call),workflow.index('Regression assertions'))
        self.assertLess(workflow.index('make target/linux/prepare V=s'),workflow.index(call))
        calls=[line.strip() for line in (ROOT/'.github/workflows/lint.yml').read_text().splitlines()
               if 'tests/test-nss-command-gate.py' in line]
        self.assertEqual(len(calls),1)
        self.assertIn(calls[0],('python3 tests/test-nss-command-gate.py','python3 -B tests/test-nss-command-gate.py'))

    def test_selector_zero_duplicate_symlink_nested_partial_find_failure(self):
        _,script=self.step()
        bash=os.environ.get('AX6_TEST_BASH') or shutil.which('bash')
        if Path('/opt/homebrew/bin/bash').exists() and 'AX6_TEST_BASH' not in os.environ: bash='/opt/homebrew/bin/bash'
        for drivers,clients,mode in [(0,1,''),(1,0,''),(2,1,''),(1,2,''),(1,1,''),
            (1,1,'nested'),(0,1,'nested'),(0,1,'symlink'),(1,0,'symlink-clients'),
            (1,1,'partial-find'),(1,1,'partial-find-clients')]:
            with self.subTest(drivers=drivers,clients=clients,mode=mode),tempfile.TemporaryDirectory() as temp:
                root=Path(temp); prepared=root/'build_dir/target-aarch64_cortex-a53_musl/linux-qualcommax_ipq807x'; prepared.mkdir(parents=True)
                for prefix,count in [('qca-nss-drv',drivers),('qca-nss-clients',clients)]:
                    for i in range(count): (prepared/(prefix+'-'+str(i))).mkdir()
                if mode=='nested': (prepared/'old/quarantine/qca-nss-drv-stale').mkdir(parents=True)
                if mode.startswith('symlink'):
                    prefix='qca-nss-clients' if mode=='symlink-clients' else 'qca-nss-drv'
                    (root/'foreign').mkdir(); (prepared/(prefix+'-link')).symlink_to(root/'foreign',target_is_directory=True)
                binary=root/'bin'; binary.mkdir(); recorder=binary/'python3'
                recorder.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$NSS_TEST_RECORD"\n'); recorder.chmod(0o755)
                if mode=='partial-find':
                    fake=binary/'find'; fake.write_text('#!/bin/sh\nprintf "%s\\000" "$1/qca-nss-drv-0"\nexit 7\n'); fake.chmod(0o755)
                if mode=='partial-find-clients':
                    fake=binary/'find'
                    fake.write_text('#!/bin/sh\ncase "$7" in qca-nss-drv-*) printf "%s\\000" "$1/qca-nss-drv-0"; exit 0;; esac\nprintf "%s\\000" "$1/qca-nss-clients-0"\nexit 7\n')
                    fake.chmod(0o755)
                record=root/'argv'; env=dict(os.environ,PATH=str(binary)+os.pathsep+os.environ['PATH'],GITHUB_WORKSPACE=str(root),NSS_TEST_RECORD=str(record))
                ran=subprocess.run([bash,'-s'],input=script,cwd=root,env=env,text=True,capture_output=True,timeout=10)
                expected=drivers==clients==1 and not mode.startswith('partial-find')
                self.assertEqual(ran.returncode==0,expected,ran.stderr); self.assertEqual(record.exists(),expected)
                if mode.startswith('partial-find'): self.assertEqual(ran.returncode,7)
                if expected:
                    argv=record.read_text().splitlines()
                    self.assertEqual(argv[argv.index('--source-root')+1],str(root/'core-accepted-source'))
                    self.assertEqual(argv[argv.index('--driver')+1],str(root/'core-flow-evidence/nss-command-inputs/root-host/driver25-prefix'))
                    self.assertEqual(argv[argv.index('--clients')+1],str(prepared.relative_to(root)/'qca-nss-clients-0'))


if __name__ == '__main__':
    unittest.main()
