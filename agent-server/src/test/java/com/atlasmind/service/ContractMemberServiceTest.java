package com.atlasmind.service;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.jdbc.JdbcTest;
import org.springframework.context.annotation.Import;
import org.springframework.jdbc.core.JdbcTemplate;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

@JdbcTest(properties = {
        "spring.datasource.url=jdbc:h2:mem:member;MODE=MySQL;DATABASE_TO_LOWER=TRUE;DB_CLOSE_DELAY=-1"
})
@Import(ContractMemberService.class)
class ContractMemberServiceTest {

    @Autowired
    private JdbcTemplate jdbc;

    @Autowired
    private ContractMemberService memberService;

    @BeforeEach
    void setUp() {
        jdbc.execute("DROP TABLE IF EXISTS contract_member");
        jdbc.execute("DROP TABLE IF EXISTS contract_case");
        jdbc.execute("""
                CREATE TABLE contract_member (
                    id BIGINT AUTO_INCREMENT PRIMARY KEY,
                    case_id BIGINT NOT NULL,
                    user_id BIGINT NOT NULL,
                    role VARCHAR(16) NOT NULL DEFAULT 'VIEWER',
                    status VARCHAR(16) NOT NULL DEFAULT 'ACTIVE',
                    invited_by BIGINT,
                    joined_at TIMESTAMP,
                    removed_at TIMESTAMP,
                    create_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    update_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (case_id, user_id)
                )
                """);
        jdbc.execute("""
                CREATE TABLE contract_case (
                    id BIGINT PRIMARY KEY,
                    owner_id BIGINT,
                    maintainer_id BIGINT,
                    deleted TINYINT DEFAULT 0
                )
                """);
        jdbc.update("INSERT INTO contract_case (id) VALUES (100)");
        jdbc.execute("DROP TABLE IF EXISTS t_user");
        jdbc.execute("""
                CREATE TABLE t_user (
                    id BIGINT PRIMARY KEY,
                    username VARCHAR(64) NOT NULL,
                    nickname VARCHAR(64),
                    avatar VARCHAR(256)
                )
                """);
        jdbc.update("INSERT INTO t_user (id,username,nickname) VALUES (1,'alice','Alice')");
        jdbc.update("INSERT INTO t_user (id,username,nickname) VALUES (2,'bob','Bob')");
        jdbc.update("INSERT INTO t_user (id,username,nickname) VALUES (3,'charlie','Charlie')");
    }

    @Test
    void addOwnerCreatesOwnership() {
        memberService.addOwner(100L, 1L);

        assertThat(memberService.isMember(100L, 1L)).isTrue();
        assertThat(memberService.getMemberRole(100L, 1L)).isEqualTo("OWNER");
    }

    @Test
    void addOwnerIsIdempotent() {
        memberService.addOwner(100L, 1L);
        memberService.addOwner(100L, 1L);

        var members = memberService.listMembers(100L);
        assertThat(members).hasSize(1);
        assertThat(members.get(0).get("role")).isEqualTo("OWNER");
    }

    @Test
    void inviteMemberAddsNonOwnerRole() {
        memberService.addOwner(100L, 1L);
        memberService.inviteMember(100L, 2L, "EDITOR", 1L);

        assertThat(memberService.isMember(100L, 2L)).isTrue();
        assertThat(memberService.getMemberRole(100L, 2L)).isEqualTo("EDITOR");
    }

    @Test
    void inviteMemberRejectsOwnerRole() {
        memberService.addOwner(100L, 1L);

        assertThatThrownBy(() -> memberService.inviteMember(100L, 2L, "OWNER", 1L))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("转移所有权");
    }

    @Test
    void invitedMemberCanBeUpgraded() {
        memberService.addOwner(100L, 1L);
        memberService.inviteMember(100L, 2L, "VIEWER", 1L);
        memberService.updateMemberRole(100L, 2L, "EDITOR", 1L);

        assertThat(memberService.getMemberRole(100L, 2L)).isEqualTo("EDITOR");
    }

    @Test
    void editorCannotChangeOwner() {
        memberService.addOwner(100L, 1L);
        memberService.inviteMember(100L, 2L, "EDITOR", 1L);

        // EDITOR (user 2) cannot change OWNER's (user 1) role
        assertThatThrownBy(() -> memberService.updateMemberRole(100L, 1L, "VIEWER", 2L))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("OWNER");
    }

    @Test
    void lastOwnerCannotBeRemoved() {
        memberService.addOwner(100L, 1L);

        assertThatThrownBy(() -> memberService.removeMember(100L, 1L, 1L))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("唯一 OWNER");
    }

    @Test
    void ownerCanRemoveAfterAddingSecondOwner() {
        memberService.addOwner(100L, 1L);
        // Transfer ownership to user 2, downgrading user 1 to EDITOR
        memberService.transferOwnership(100L, 2L, 1L);

        // Now user 2 is OWNER, user 1 is EDITOR
        assertThat(memberService.getMemberRole(100L, 2L)).isEqualTo("OWNER");
        assertThat(memberService.getMemberRole(100L, 1L)).isEqualTo("EDITOR");

        // User 2 (OWNER) can remove user 1 (EDITOR)
        memberService.removeMember(100L, 1L, 2L);
        assertThat(memberService.isMember(100L, 1L)).isFalse();
    }

    @Test
    void nonOwnerCannotTransferOwnership() {
        memberService.addOwner(100L, 1L);
        memberService.inviteMember(100L, 2L, "EDITOR", 1L);

        assertThatThrownBy(() -> memberService.transferOwnership(100L, 3L, 2L))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("OWNER");
    }

    @Test
    void ownerCannotTransferToSelf() {
        memberService.addOwner(100L, 1L);

        assertThatThrownBy(() -> memberService.transferOwnership(100L, 1L, 1L))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("自己");
    }

    @Test
    void forceSetOwnerOverwritesExistingOwner() {
        memberService.addOwner(100L, 1L);
        memberService.inviteMember(100L, 2L, "EDITOR", 1L);

        // ADMIN forces user 3 to be the new owner
        memberService.forceSetOwner(100L, 3L);

        assertThat(memberService.getMemberRole(100L, 3L)).isEqualTo("OWNER");
        // Previous owner 1 should be downgraded to EDITOR
        assertThat(memberService.getMemberRole(100L, 1L)).isEqualTo("EDITOR");
    }

    @Test
    void forceSetOwnerFixesOwnerlessContract() {
        // Simulate a broken state: no OWNER (e.g., self-transfer bug aftermath)
        jdbc.update("INSERT INTO contract_member (case_id, user_id, role, status) VALUES (?,?,?,?)",
                100L, 1L, "EDITOR", "ACTIVE");
        jdbc.update("INSERT INTO contract_member (case_id, user_id, role, status) VALUES (?,?,?,?)",
                100L, 2L, "VIEWER", "ACTIVE");

        memberService.forceSetOwner(100L, 2L);

        assertThat(memberService.getMemberRole(100L, 2L)).isEqualTo("OWNER");
        assertThat(memberService.getMemberRole(100L, 1L)).isEqualTo("EDITOR");
    }

    @Test
    void transferOwnershipSyncsContractCaseOwnerId() {
        memberService.addOwner(100L, 1L);
        memberService.inviteMember(100L, 2L, "EDITOR", 1L);

        memberService.transferOwnership(100L, 2L, 1L);

        // contract_case.owner_id must reflect the new owner
        var row = jdbc.queryForMap("SELECT owner_id, maintainer_id FROM contract_case WHERE id=100");
        assertThat(((Number) row.get("owner_id")).longValue()).isEqualTo(2L);
        assertThat(((Number) row.get("maintainer_id")).longValue()).isEqualTo(2L);
    }

    @Test
    void forceSetOwnerSyncsContractCaseOwnerId() {
        memberService.addOwner(100L, 1L);
        memberService.forceSetOwner(100L, 3L);

        var row = jdbc.queryForMap("SELECT owner_id, maintainer_id FROM contract_case WHERE id=100");
        assertThat(((Number) row.get("owner_id")).longValue()).isEqualTo(3L);
        assertThat(((Number) row.get("maintainer_id")).longValue()).isEqualTo(3L);
    }

    @Test
    void removedMemberCannotAccess() {
        memberService.addOwner(100L, 1L);
        memberService.inviteMember(100L, 2L, "VIEWER", 1L);
        memberService.removeMember(100L, 2L, 1L);

        assertThat(memberService.isMember(100L, 2L)).isFalse();
        assertThat(memberService.getMemberRole(100L, 2L)).isNull();
    }

    @Test
    void permissionChecksReflectRole() {
        memberService.addOwner(100L, 1L);            // OWNER
        memberService.inviteMember(100L, 2L, "EDITOR", 1L);
        memberService.inviteMember(100L, 3L, "VIEWER", 1L);

        // OWNER can do everything
        assertThat(memberService.canWrite(100L, 1L)).isTrue();
        assertThat(memberService.canReview(100L, 1L)).isTrue();
        assertThat(memberService.canManageMembers(100L, 1L)).isTrue();

        // EDITOR can write and review, not manage members
        assertThat(memberService.canWrite(100L, 2L)).isTrue();
        assertThat(memberService.canReview(100L, 2L)).isTrue();
        assertThat(memberService.canManageMembers(100L, 2L)).isFalse();

        // VIEWER is read-only
        assertThat(memberService.canWrite(100L, 3L)).isFalse();
        assertThat(memberService.canReview(100L, 3L)).isFalse();
        assertThat(memberService.canManageMembers(100L, 3L)).isFalse();
    }

    @Test
    void listMembersIncludesUserInfo() {
        memberService.addOwner(100L, 1L);
        memberService.inviteMember(100L, 2L, "VIEWER", 1L);

        var members = memberService.listMembers(100L);
        assertThat(members).hasSize(2);
        assertThat(members.get(0).get("username")).isEqualTo("alice");
        assertThat(members.get(1).get("username")).isEqualTo("bob");
    }

    @Test
    void nonMemberHasNoRole() {
        assertThat(memberService.getMemberRole(100L, 1L)).isNull();
        assertThat(memberService.isMember(100L, 1L)).isFalse();
    }
}
