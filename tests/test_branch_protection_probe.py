import unittest


class BranchProtectionProbe(unittest.TestCase):
    def test_required_gate_blocks_merge(self):
        self.fail("intentional branch-protection probe; never merge this branch")
