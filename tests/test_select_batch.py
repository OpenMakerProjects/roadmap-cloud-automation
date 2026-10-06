import importlib.util, pathlib, tempfile, unittest
spec=importlib.util.spec_from_file_location('selector', pathlib.Path(__file__).resolve().parents[1]/'scripts/select_batch.py')
selector=importlib.util.module_from_spec(spec);spec.loader.exec_module(selector)
class SelectionTests(unittest.TestCase):
    def test_audit_cannot_regress_publication(self):
        with tempfile.TemporaryDirectory() as t:
            p=pathlib.Path(t)
            (p/'publish-results-seed.csv').write_text('Id,Status,Error\n1,failed,"multiline\nerror"\n1,published,\n2,failed,\n')
            (p/'daily-results.csv').write_text('Id,Status\n1,blocked\n2,published\n')
            self.assertEqual(selector.latest_statuses(p), {1:'published',2:'published'})
    def test_publication_is_not_completion(self):
        projects=[{'id':1},{'id':2},{'id':3}]
        self.assertEqual(selector.select(projects,{},20),projects)
        self.assertEqual(selector.select(projects,{'1':{'status':'verified_complete'}},20),projects[1:])
        self.assertEqual(selector.select(projects,{'1':{'status':'blocked'}},20),projects)
if __name__=='__main__': unittest.main()
