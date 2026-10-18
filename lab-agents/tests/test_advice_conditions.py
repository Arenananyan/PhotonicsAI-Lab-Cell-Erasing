import tempfile
import unittest

from agents.advice import ranked_cells, suggestion_catalog, validate_recommendations
from agents.contracts import validate_task
from agents.planning import HOME
from agents.workflow import Workflow
from test_autonomous import Printer, Scripted, task


def conditioned(operation, metric='blue_count', operator='gt', value=1, compare_metric=None):
    return dict(task(operation), condition=dict(metric=metric,operator=operator,
                                               value=value,compare_metric=compare_metric))


class AdviceAndConditions(unittest.IsolatedAsyncioTestCase):
    async def test_false_condition_reports_without_preview_or_motion(self):
        with tempfile.TemporaryDirectory() as directory:
            tools=Printer();tools.position=HOME[:]
            flow=Workflow(tools,Scripted(conditioned('wipe',value=3)),directory,demo=True)
            rid=flow.new('Եթե կապույտները 3-ից շատ են, մաքրիր բոլոր կապույտները')
            await flow.prepare(rid)
            run=flow.get(rid)
            self.assertEqual(run['state'],'observed')
            self.assertFalse(run['condition_result']['passed'])
            self.assertIsNone(run.get('plan'))
            self.assertEqual(tools.moves,[])
            self.assertFalse(run['motion_sent'])

    async def test_true_condition_still_requires_full_path_approval(self):
        with tempfile.TemporaryDirectory() as directory:
            tools=Printer();tools.position=HOME[:]
            flow=Workflow(tools,Scripted(conditioned('wipe')),directory,demo=True)
            rid=flow.new('If there are more than one blue cells, clean all blue cells')
            await flow.prepare(rid)
            run=flow.get(rid)
            self.assertTrue(run['condition_result']['passed'])
            self.assertEqual(run['state'],'awaiting_confirmation')
            self.assertEqual(run['phase'],'wipe')
            self.assertTrue(run['plan']['waypoints'])
            self.assertEqual(tools.moves,[])
            self.assertIsNone(run.get('authorization'))

    async def test_condition_away_from_home_does_not_move(self):
        with tempfile.TemporaryDirectory() as directory:
            tools=Printer();flow=Workflow(tools,Scripted(conditioned('wipe')),directory,demo=True)
            rid=flow.new('If blue count is above one, clean all blue')
            await flow.prepare(rid)
            self.assertEqual(flow.get(rid)['state'],'awaiting_answer')
            self.assertEqual(tools.moves,[])

    async def test_dropped_condition_and_else_branch_never_preview(self):
        for prompt in ('If there are more than three blue cells, clean all blue cells',
                       'Եթե կապույտները շատ են, մաքրիր դրանք, այլապես գնա տուն'):
            with self.subTest(prompt=prompt),tempfile.TemporaryDirectory() as directory:
                tools=Printer();tools.position=HOME[:]
                flow=Workflow(tools,Scripted(task('wipe')),directory,demo=True)
                rid=flow.new(prompt)
                await flow.prepare(rid)
                self.assertEqual(flow.get(rid)['state'],'awaiting_answer')
                self.assertIsNone(flow.get(rid).get('plan'))
                self.assertEqual(tools.moves,[])

    async def test_ranked_report_and_suggestions_are_read_only(self):
        with tempfile.TemporaryDirectory() as directory:
            tools=Printer();flow=Workflow(tools,Scripted(task('inspect')),directory,demo=True)
            rid=flow.new('Show blue and green cells from largest to smallest')
            await flow.prepare(rid)
            run=flow.get(rid)
            self.assertEqual(run['state'],'observed')
            self.assertEqual([(c['color'],c['area_mm2']) for c in run['ranked_cells']],
                             [('blue',150),('blue',40),('green',60)])
            self.assertTrue(run['suggestions'])
            self.assertEqual(tools.moves,[])

    def test_unmeasured_cells_never_receive_wipe_suggestions(self):
        observation=dict(available=False,error='Stale frame')
        self.assertEqual(ranked_cells(observation),[])
        catalog=suggestion_catalog({},[],english=True)
        self.assertFalse(any(item['id'].startswith(('largest','all')) for item in catalog))

    def test_hallucinated_or_duplicate_suggestions_are_rejected(self):
        catalog=suggestion_catalog({},[],english=True)
        for ids in (['wipe_everything'],['status','status'],['status']*4):
            with self.subTest(ids=ids),self.assertRaises(ValueError):
                validate_recommendations(dict(suggestion_ids=ids),catalog)

    def test_invalid_or_unsupported_conditions_fail_closed(self):
        for condition in (
            dict(metric='fiction',operator='gt',value=1,compare_metric=None),
            dict(metric='blue_count',operator='gt',value=1,compare_metric='green_count'),
            dict(metric='blue_count',operator='gt',value=None,compare_metric=None),
            dict(metric='blue_count',operator='gt',value=float('nan'),compare_metric=None),
        ):
            with self.subTest(condition=condition),self.assertRaises(ValueError):
                validate_task(dict(task(),condition=condition))
