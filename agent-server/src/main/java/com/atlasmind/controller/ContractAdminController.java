package com.atlasmind.controller;

import com.atlasmind.common.Result;
import lombok.RequiredArgsConstructor;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.Map;

@RestController
@RequiredArgsConstructor
@RequestMapping("/api/admin/contracts")
public class ContractAdminController {

    private final JdbcTemplate jdbc;

    // ── Review Rules ──────────────────────────────────────────────

    @GetMapping("/rules")
    public Result<List<Map<String, Object>>> listRules() {
        return Result.ok(jdbc.queryForList(
            "SELECT id, rule_key AS ruleKey, rule_set AS ruleSet, clause_type AS clauseType, title, description, check_type AS checkType, check_config AS checkConfig, severity, weight, is_veto AS isVeto, is_active AS isActive, version, create_time AS createTime FROM contract_review_rule ORDER BY rule_set, clause_type, id"));
    }

    @PostMapping("/rules")
    public Result<Map<String, Object>> createRule(@RequestBody Map<String, Object> r) {
        jdbc.update("INSERT INTO contract_review_rule (rule_key, rule_set, clause_type, title, description, check_type, check_config, severity, weight, is_veto, is_active, version)"
            + " VALUES (?,?,?,?,?,?,?,?,?,?,?,1)",
            r.get("ruleKey"), r.get("ruleSet"), r.get("clauseType"), r.get("title"), r.get("description"),
            r.getOrDefault("checkType", "MISSING"), r.get("checkConfig"), r.getOrDefault("severity", "MEDIUM"),
            r.getOrDefault("weight", 10), r.getOrDefault("isVeto", 0), r.getOrDefault("isActive", 1));
        return Result.ok(Map.of("created", true));
    }

    @PutMapping("/rules/{id}")
    public Result<Map<String, Object>> updateRule(@PathVariable Long id, @RequestBody Map<String, Object> r) {
        java.util.List<String> sets = new java.util.ArrayList<>();
        java.util.List<Object> params = new java.util.ArrayList<>();
        for (String f : new String[]{"title","description","severity","weight","checkType","checkConfig"}) {
            if (r.containsKey(f)) { sets.add(f + "=?"); params.add(r.get(f)); }
        }
        if (r.containsKey("isActive")) { sets.add("is_active=?"); params.add(r.get("isActive")); }
        if (r.containsKey("isVeto")) { sets.add("is_veto=?"); params.add(r.get("isVeto")); }
        if (!sets.isEmpty()) { params.add(id); jdbc.update("UPDATE contract_review_rule SET " + String.join(",", sets) + " WHERE id=?", params.toArray()); }
        return Result.ok(Map.of("updated", true));
    }

    @DeleteMapping("/rules/{id}")
    public Result<Map<String, Object>> deleteRule(@PathVariable Long id) {
        jdbc.update("DELETE FROM contract_review_rule WHERE id=?", id);
        return Result.ok(Map.of("deleted", true));
    }

    // ── Standard Clauses ──────────────────────────────────────────

    @GetMapping("/clauses")
    public Result<List<Map<String, Object>>> listClauses() {
        return Result.ok(jdbc.queryForList(
            "SELECT id, clause_type AS clauseType, title, content, semantic_elements AS semanticElements, is_mandatory AS isMandatory, negotiation_bottom_line AS negotiationBottomLine, version, is_active AS isActive, effective_from AS effectiveFrom, effective_to AS effectiveTo, create_time AS createTime FROM contract_standard_clause ORDER BY clause_type, id"));
    }

    @PostMapping("/clauses")
    public Result<Map<String, Object>> createClause(@RequestBody Map<String, Object> r) {
        jdbc.update("INSERT INTO contract_standard_clause (clause_type, title, content, semantic_elements, is_mandatory, negotiation_bottom_line, is_active, version)"
            + " VALUES (?,?,?,?,?,?,?,1)",
            r.get("clauseType"), r.get("title"), r.get("content"), r.get("semanticElements"),
            r.getOrDefault("isMandatory", 0), r.get("negotiationBottomLine"), r.getOrDefault("isActive", 1));
        return Result.ok(Map.of("created", true));
    }

    @PutMapping("/clauses/{id}")
    public Result<Map<String, Object>> updateClause(@PathVariable Long id, @RequestBody Map<String, Object> r) {
        StringBuilder sql = new StringBuilder("UPDATE contract_standard_clause SET ");
        java.util.List<Object> params = new java.util.ArrayList<>();
        for (String f : new String[]{"title","content","semanticElements","negotiationBottomLine"}) {
            if (r.containsKey(f)) { sql.append(f).append("=?,"); params.add(r.get(f)); }
        }
        if (r.containsKey("isActive")) { sql.append("is_active=?,"); params.add(r.get("isActive")); }
        if (r.containsKey("isMandatory")) { sql.append("is_mandatory=?,"); params.add(r.get("isMandatory")); }
        sql.setLength(sql.length() - 1);
        sql.append(" WHERE id=?"); params.add(id);
        jdbc.update(sql.toString(), params.toArray());
        return Result.ok(Map.of("updated", true));
    }

    @DeleteMapping("/clauses/{id}")
    public Result<Map<String, Object>> deleteClause(@PathVariable Long id) {
        jdbc.update("DELETE FROM contract_standard_clause WHERE id=?", id);
        return Result.ok(Map.of("deleted", true));
    }
}
