import unittest

from app.agent_runtime.scoring import HealthScoringEngine
from app.agent_runtime.tools import AgentToolRegistry


class AgentToolRegistryContractTest(unittest.TestCase):
    def test_documents_the_only_supported_tool_names(self):
        registry = AgentToolRegistry(object(), object(), HealthScoringEngine())

        self.assertTrue(registry.supports("searchProjectEvidence"))
        self.assertTrue(registry.supports("calculateHealthScore"))
        self.assertTrue(registry.supports("searchSourceCode"))
        self.assertTrue(registry.supports("readSourceFile"))
        self.assertFalse(registry.supports("executeSql"))
        self.assertFalse(registry.supports("createGithubIssue"))


if __name__ == "__main__":
    unittest.main()
