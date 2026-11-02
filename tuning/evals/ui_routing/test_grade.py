import unittest
from tuning.evals.ui_routing.grade import grade

class IntentGradeTests(unittest.TestCase):
 def out(self,decision,**kw):return {'id':'test','needs_clarification':False,'plans':[{'decisions':decision,'skills':[]}],**kw}
 def test_resolver_success_cannot_launder_wrong_non_ui_intent(self):
  r=grade('test',{}, {'required':[],'optional':[]},self.out(['visual-direction']))
  self.assertFalse(r['passed']);self.assertIn('UNNECESSARY_SKILL_LOADED',r['reasons'])
 def test_missing_mandatory_and_optional_cost_separate(self):
  r=grade('test',{}, {'required':['async-state-reliability','impeccable'],'optional':['playwright-cli']},self.out(['hardening','browser']))
  self.assertFalse(r['passed']);self.assertEqual(r['metrics']['missing_skills'],1);self.assertEqual(r['metrics']['optional_skills_loaded'],1)
 def test_declared_missing_capability_is_blocked_not_substituted(self):
  r=grade('test',{}, {'required':['pencilplaybook'],'status':'UI_ROUTE_BLOCKED'},self.out(['pencil-design']))
  self.assertTrue(r['passed'])
 def test_variant_order_is_free_but_authority_mixing_is_not(self):
  e={'variants':[['hallmark'],['design-taste-frontend']]}
  plans=[{'decisions':['taste-design'],'skills':[]},{'decisions':['hallmark-design'],'skills':[]}]
  self.assertTrue(grade('test',{},e,self.out([],plans=plans))['passed'])
  self.assertFalse(grade('test',{},e,self.out(['taste-design','hallmark-design']))['passed'])
 def test_clarification_must_not_load_a_skill_bundle(self):
  self.assertTrue(grade('test',{}, {'clarify':True},self.out([],plans=[],needs_clarification=True))['passed'])
  self.assertFalse(grade('test',{}, {'clarify':True},self.out(['backend-only'],needs_clarification=True))['passed'])
if __name__=='__main__':unittest.main()
