import unittest

from app.agent_runtime.scoring import HealthScoringEngine


def citation(source_id: str, object_type: str, snippet: str) -> dict:
    return {
        "sourceType": "GITHUB",
        "sourceId": source_id,
        "objectType": object_type,
        "sourceRef": object_type,
        "title": object_type,
        "snippet": snippet,
    }


class HealthScoringEngineTest(unittest.TestCase):
    def setUp(self):
        self.engine = HealthScoringEngine()

    def test_identical_evidence_produces_identical_score_and_hash(self):
        project = {
            "id": 9,
            "repositoryUrl": "https://github.com/acme/repo",
            "currentMilestone": "MVP",
            "releaseTarget": "2026-Q3",
            "techStack": "Java",
            "teamSize": 3,
        }
        evidence = [
            citation("1", "README", "README with JUnit tests and .github/workflows/ci.yml"),
            citation("2", "COMMIT", "Add package configuration"),
        ]

        first = self.engine.score(project, evidence)
        second = self.engine.score(project, evidence)

        self.assertEqual(first["healthScore"], second["healthScore"])
        self.assertEqual(first["evidenceHash"], second["evidenceHash"])

    def test_changed_evidence_changes_the_snapshot_hash(self):
        project = {"id": 9, "repositoryUrl": "repo"}

        first = self.engine.evidence_hash(project, [citation("1", "README", "old")])
        second = self.engine.evidence_hash(project, [citation("1", "README", "new")])

        self.assertNotEqual(first, second)


if __name__ == "__main__":
    unittest.main()
