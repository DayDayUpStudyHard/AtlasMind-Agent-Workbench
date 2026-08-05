import unittest

from app.agent_runtime.contract_store import _fuse_contract_retrieval


class ContractRetrievalTest(unittest.TestCase):
    def test_es_vector_and_keyword_agreement_is_explicit(self):
        vector = [{"clauseId": 10, "content": "工程移交生产后结算", "score": 0.91}]
        keyword = [{"clauseId": 10, "content": "工程移交生产后结算", "score": 0}]

        hits, validation = _fuse_contract_retrieval(vector, keyword, 5)

        self.assertEqual(1, len(hits))
        self.assertTrue(hits[0]["crossValidated"])
        self.assertEqual(["ES_VECTOR", "MYSQL_KEYWORD"], hits[0]["retrievalSources"])
        self.assertEqual("MULTI_SOURCE", hits[0]["retrievalAgreement"])
        self.assertEqual(1, validation["vectorKeywordOverlap"])
        self.assertEqual(1, validation["crossValidatedCount"])

    def test_single_es_hit_is_not_presented_as_cross_validated(self):
        hits, validation = _fuse_contract_retrieval(
            [{"clauseId": 11, "content": "付款条件", "score": 0.8}],
            [],
            5,
        )

        self.assertFalse(hits[0]["crossValidated"])
        self.assertEqual("SINGLE_SOURCE", hits[0]["retrievalAgreement"])
        self.assertEqual(0, validation["crossValidatedCount"])

    def test_mysql_is_an_independent_cross_check_when_es_is_available(self):
        hits, validation = _fuse_contract_retrieval(
            [{"clauseId": 12, "content": "向量命中", "score": 0.8}],
            [{"clauseId": 12, "content": "关键词命中", "score": 0}],
            5,
        )

        self.assertTrue(hits[0]["crossValidated"])
        self.assertEqual(["ES_VECTOR", "MYSQL_KEYWORD"], hits[0]["retrievalSources"])
        self.assertEqual(1, validation["vectorKeywordOverlap"])


if __name__ == "__main__":
    unittest.main()
