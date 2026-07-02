import Foundation

struct ActivityPayload: Decodable {
    var workspace: WorkspacePayload?
    var onboarding: OnboardingPayload?
    var sharedServer: SharedServerPayload?
    var activity: ActivityFeed?
    var status: StatusPayload?
    var workflow: WorkflowPayload?

    enum CodingKeys: String, CodingKey {
        case workspace
        case onboarding
        case sharedServer = "shared_server"
        case activity
        case status
        case workflow
    }
}

struct SharedServerPayload: Decodable {
    var configured: Bool?
    var status: String?
    var configPath: String?
    var baseURL: String?
    var graphSlug: String?
    var userID: String?
    var tokenConfigured: Bool?
    var remoteOK: Bool?
    var error: String?
    var me: SharedServerUserPayload?
    var team: SharedServerTeamPayload?
    var capabilities: SharedServerCapabilitiesPayload?
    var capabilitiesError: String?

    enum CodingKeys: String, CodingKey {
        case configured
        case status
        case configPath = "config_path"
        case baseURL = "base_url"
        case graphSlug = "graph_slug"
        case userID = "user_id"
        case tokenConfigured = "token_configured"
        case remoteOK = "remote_ok"
        case error
        case me
        case team
        case capabilities
        case capabilitiesError = "capabilities_error"
    }
}

struct SharedServerCapabilitiesPayload: Decodable {
    var service: String?
    var apiVersion: Int?
    var features: [String]?
    var capabilities: [String: Bool]?
    var security: SharedServerSecurityPayload?

    enum CodingKeys: String, CodingKey {
        case service
        case apiVersion = "api_version"
        case features
        case capabilities
        case security
    }
}

struct SharedServerSecurityPayload: Decodable {
    var defaultInviteTokenExpirationDays: Int?

    enum CodingKeys: String, CodingKey {
        case defaultInviteTokenExpirationDays = "default_invite_token_expiration_days"
    }
}

struct SharedServerUserPayload: Decodable {
    var id: String?
    var email: String?
    var name: String?
    var isAdmin: Bool?

    enum CodingKeys: String, CodingKey {
        case id
        case email
        case name
        case isAdmin = "is_admin"
    }
}

struct SharedServerTeamPayload: Decodable {
    var repo: String?
    var canListUsers: Bool?
    var canListGrants: Bool?
    var canListTokens: Bool?
    var canListPolicies: Bool?
    var canReadPolicy: Bool?
    var canReadAuditIntegrity: Bool?
    var canReadRelationPolicyConflicts: Bool?
    var canReadInviteExpirationSummary: Bool?
    var canReadStorageStatus: Bool?
    var usersCount: Int?
    var activeUsersCount: Int?
    var disabledUsersCount: Int?
    var grantsCount: Int?
    var disabledGrantsCount: Int?
    var activeOwnerGrantsCount: Int?
    var disabledOwnerGrantsCount: Int?
    var lastOwnerGrantRisk: Bool?
    var tokensCount: Int?
    var activeTokensCount: Int?
    var activeTokensWithLastUsedCount: Int?
    var activeTokensNeverUsedCount: Int?
    var activeTokensWithoutExpirationCount: Int?
    var staleActiveTokensCount: Int?
    var staleTokenDays: Int?
    var expiredTokensCount: Int?
    var revokedTokensCount: Int?
    var disabledTokensCount: Int?
    var tokensWithLastUsedCount: Int?
    var latestTokenLastUsedAt: String?
    var latestActiveTokenLastUsedAt: String?
    var oldestActiveTokenLastUsedAt: String?
    var policiesCount: Int?
    var constrainedPoliciesCount: Int?
    var disabledSharedPolicyCount: Int?
    var disabledPersonalPolicyCount: Int?
    var policyInventoryRepoFilterPresent: Bool?
    var effectivePolicyRepo: String?
    var effectivePolicyInheritedFrom: String?
    var effectivePolicyVersionNS: String?
    var effectivePolicyFingerprint: String?
    var effectivePolicyRelationLabelCount: Int?
    var effectivePolicyMinFactRating: Double?
    var effectivePolicySharedRelationsAllowed: Bool?
    var effectivePolicyPersonalRelationsAllowed: Bool?
    var effectivePolicyConstrained: Bool?
    var roleCounts: [String: Int]?
    var tokenRoleCounts: [String: Int]?
    var auditIntegrity: SharedServerAuditIntegrityPayload?
    var relationPolicyConflictCount: Int?
    var relationPolicyConflictScopeCounts: [String: Int]?
    var relationPolicyConflictCurrentReasonCounts: [String: Int]?
    var latestRelationPolicyConflictAt: String?
    var inviteExpirationAuditCount: Int?
    var inviteExpirationDefaultedCount: Int?
    var inviteExpirationExplicitCount: Int?
    var inviteExpirationUnknownCount: Int?
    var latestInviteExpirationAuditAt: String?
    var storageOK: Bool?
    var storageBackend: String?
    var storageCheckedAt: String?
    var storageUserCount: Int?
    var storageDisabledUserCount: Int?
    var storageSharedGraphCount: Int?
    var storageSharedMemoryCount: Int?
    var storageActiveSharedMemoryCount: Int?
    var storageArchivedSharedMemoryCount: Int?
    var storageSharedRelationCount: Int?
    var storagePersonalRelationCount: Int?
    var storageTokenCount: Int?
    var storageActiveTokenCount: Int?
    var storageRevokedTokenCount: Int?
    var storageExpiredTokenCount: Int?
    var storageAuditEventCount: Int?
    var storageTokenHygieneStaleAfterDays: Int?
    var storageTokenHygieneStaleCutoffAt: String?
    var storageActiveTokensWithoutExpirationCount: Int?
    var storageActiveTokensNeverUsedCount: Int?
    var storageStaleActiveTokensCount: Int?
    var storageActiveTokensForDisabledUsersCount: Int?
    var storageActiveGlobalTokensCount: Int?
    var storageActiveScopedTokensCount: Int?
    var storageAuditChainStatus: String?
    var storageAuditChainContinuityStatus: String?
    var usersError: String?
    var grantsError: String?
    var tokensError: String?
    var policiesError: String?
    var policyError: String?
    var auditIntegrityError: String?
    var relationPolicyConflictsError: String?
    var inviteExpirationSummaryError: String?
    var storageStatusError: String?

    enum CodingKeys: String, CodingKey {
        case repo
        case canListUsers = "can_list_users"
        case canListGrants = "can_list_grants"
        case canListTokens = "can_list_tokens"
        case canListPolicies = "can_list_policies"
        case canReadPolicy = "can_read_policy"
        case canReadAuditIntegrity = "can_read_audit_integrity"
        case canReadRelationPolicyConflicts = "can_read_relation_policy_conflicts"
        case canReadInviteExpirationSummary = "can_read_invite_expiration_summary"
        case canReadStorageStatus = "can_read_storage_status"
        case usersCount = "users_count"
        case activeUsersCount = "active_users_count"
        case disabledUsersCount = "disabled_users_count"
        case grantsCount = "grants_count"
        case disabledGrantsCount = "disabled_grants_count"
        case activeOwnerGrantsCount = "active_owner_grants_count"
        case disabledOwnerGrantsCount = "disabled_owner_grants_count"
        case lastOwnerGrantRisk = "last_owner_grant_risk"
        case tokensCount = "tokens_count"
        case activeTokensCount = "active_tokens_count"
        case activeTokensWithLastUsedCount = "active_tokens_with_last_used_count"
        case activeTokensNeverUsedCount = "active_tokens_never_used_count"
        case activeTokensWithoutExpirationCount = "active_tokens_without_expiration_count"
        case staleActiveTokensCount = "stale_active_tokens_count"
        case staleTokenDays = "stale_token_days"
        case expiredTokensCount = "expired_tokens_count"
        case revokedTokensCount = "revoked_tokens_count"
        case disabledTokensCount = "disabled_tokens_count"
        case tokensWithLastUsedCount = "tokens_with_last_used_count"
        case latestTokenLastUsedAt = "latest_token_last_used_at"
        case latestActiveTokenLastUsedAt = "latest_active_token_last_used_at"
        case oldestActiveTokenLastUsedAt = "oldest_active_token_last_used_at"
        case policiesCount = "policies_count"
        case constrainedPoliciesCount = "constrained_policies_count"
        case disabledSharedPolicyCount = "disabled_shared_policy_count"
        case disabledPersonalPolicyCount = "disabled_personal_policy_count"
        case policyInventoryRepoFilterPresent = "policy_inventory_repo_filter_present"
        case effectivePolicyRepo = "effective_policy_repo"
        case effectivePolicyInheritedFrom = "effective_policy_inherited_from"
        case effectivePolicyVersionNS = "effective_policy_version_ns"
        case effectivePolicyFingerprint = "effective_policy_fingerprint"
        case effectivePolicyRelationLabelCount = "effective_policy_relation_label_count"
        case effectivePolicyMinFactRating = "effective_policy_min_fact_rating"
        case effectivePolicySharedRelationsAllowed = "effective_policy_shared_relations_allowed"
        case effectivePolicyPersonalRelationsAllowed = "effective_policy_personal_relations_allowed"
        case effectivePolicyConstrained = "effective_policy_constrained"
        case roleCounts = "role_counts"
        case tokenRoleCounts = "token_role_counts"
        case auditIntegrity = "audit_integrity"
        case relationPolicyConflictCount = "relation_policy_conflict_count"
        case relationPolicyConflictScopeCounts = "relation_policy_conflict_scope_counts"
        case relationPolicyConflictCurrentReasonCounts = "relation_policy_conflict_current_reason_counts"
        case latestRelationPolicyConflictAt = "latest_relation_policy_conflict_at"
        case inviteExpirationAuditCount = "invite_expiration_audit_count"
        case inviteExpirationDefaultedCount = "invite_expiration_defaulted_count"
        case inviteExpirationExplicitCount = "invite_expiration_explicit_count"
        case inviteExpirationUnknownCount = "invite_expiration_unknown_count"
        case latestInviteExpirationAuditAt = "latest_invite_expiration_audit_at"
        case storageOK = "storage_ok"
        case storageBackend = "storage_backend"
        case storageCheckedAt = "storage_checked_at"
        case storageUserCount = "storage_user_count"
        case storageDisabledUserCount = "storage_disabled_user_count"
        case storageSharedGraphCount = "storage_shared_graph_count"
        case storageSharedMemoryCount = "storage_shared_memory_count"
        case storageActiveSharedMemoryCount = "storage_active_shared_memory_count"
        case storageArchivedSharedMemoryCount = "storage_archived_shared_memory_count"
        case storageSharedRelationCount = "storage_shared_relation_count"
        case storagePersonalRelationCount = "storage_personal_relation_count"
        case storageTokenCount = "storage_token_count"
        case storageActiveTokenCount = "storage_active_token_count"
        case storageRevokedTokenCount = "storage_revoked_token_count"
        case storageExpiredTokenCount = "storage_expired_token_count"
        case storageAuditEventCount = "storage_audit_event_count"
        case storageTokenHygieneStaleAfterDays = "storage_token_hygiene_stale_after_days"
        case storageTokenHygieneStaleCutoffAt = "storage_token_hygiene_stale_cutoff_at"
        case storageActiveTokensWithoutExpirationCount = "storage_active_tokens_without_expiration_count"
        case storageActiveTokensNeverUsedCount = "storage_active_tokens_never_used_count"
        case storageStaleActiveTokensCount = "storage_stale_active_tokens_count"
        case storageActiveTokensForDisabledUsersCount = "storage_active_tokens_for_disabled_users_count"
        case storageActiveGlobalTokensCount = "storage_active_global_tokens_count"
        case storageActiveScopedTokensCount = "storage_active_scoped_tokens_count"
        case storageAuditChainStatus = "storage_audit_chain_status"
        case storageAuditChainContinuityStatus = "storage_audit_chain_continuity_status"
        case usersError = "users_error"
        case grantsError = "grants_error"
        case tokensError = "tokens_error"
        case policiesError = "policies_error"
        case policyError = "policy_error"
        case auditIntegrityError = "audit_integrity_error"
        case relationPolicyConflictsError = "relation_policy_conflicts_error"
        case inviteExpirationSummaryError = "invite_expiration_summary_error"
        case storageStatusError = "storage_status_error"
    }
}

struct SharedServerAuditIntegrityPayload: Decodable {
    var status: String?
    var eventCount: Int?
    var integrityCounts: [String: Int]?
    var chain: SharedServerAuditChainPayload?

    enum CodingKeys: String, CodingKey {
        case status
        case eventCount = "event_count"
        case integrityCounts = "integrity_counts"
        case chain
    }
}

struct SharedServerAuditChainPayload: Decodable {
    var status: String?
    var checkedPairs: Int?
    var linkedPairs: Int?
    var uncheckablePairs: Int?
    var chainBreakCount: Int?
    var externalGapCount: Int?

    enum CodingKeys: String, CodingKey {
        case status
        case checkedPairs = "checked_pairs"
        case linkedPairs = "linked_pairs"
        case uncheckablePairs = "uncheckable_pairs"
        case chainBreakCount = "chain_break_count"
        case externalGapCount = "external_gap_count"
    }
}

struct OnboardingPayload: Decodable {
    var state: String?
    var empty: Bool?
    var title: String?
    var message: String?
    var nextSteps: [String]?

    enum CodingKeys: String, CodingKey {
        case state
        case empty
        case title
        case message
        case nextSteps = "next_steps"
    }
}

struct WorkspacePayload: Decodable {
    var id: String?
    var workspaceKey: String?
    var slug: String?
    var title: String?
    var rootPath: String?

    enum CodingKeys: String, CodingKey {
        case id
        case workspaceKey = "workspace_key"
        case slug
        case title
        case rootPath = "root_path"
    }
}

struct ActivityFeed: Decodable {
    var summary: String?
    var recentWrites: [MemoryWrite]?
    var recentConsults: [ConsultEvent]?
    var attention: [AttentionEvent]?

    enum CodingKeys: String, CodingKey {
        case summary
        case recentWrites = "recent_writes"
        case recentConsults = "recent_consults"
        case attention
    }
}

struct MemoryWrite: Decodable, Identifiable {
    var type: String?
    var stableKey: String?
    var kind: String?
    var memoryType: String?
    var title: String?
    var summary: String?
    var updatedAt: String?
    var source: String?
    var repositories: [String]?
    var severity: String?

    var id: String { stableKey ?? "\(title ?? "memory")-\(updatedAt ?? "")" }

    enum CodingKeys: String, CodingKey {
        case type
        case stableKey = "stable_key"
        case kind
        case memoryType = "memory_type"
        case title
        case summary
        case updatedAt = "updated_at"
        case source
        case repositories
        case severity
    }
}

struct ConsultEvent: Decodable, Identifiable {
    var type: String?
    var query: String?
    var source: String?
    var accessedAt: String?
    var memoryCount: Int?
    var memories: [ConsultMemory]?
    var severity: String?

    var id: String { "\(accessedAt ?? "")-\(source ?? "")-\(query ?? "")" }

    enum CodingKeys: String, CodingKey {
        case type
        case query
        case source
        case accessedAt = "accessed_at"
        case memoryCount = "memory_count"
        case memories
        case severity
    }
}

struct ConsultMemory: Decodable, Identifiable {
    var stableKey: String?
    var kind: String?
    var title: String?
    var summary: String?
    var accessCount: Int?

    var id: String { stableKey ?? title ?? UUID().uuidString }

    enum CodingKeys: String, CodingKey {
        case stableKey = "stable_key"
        case kind
        case title
        case summary
        case accessCount = "access_count"
    }
}

struct AttentionEvent: Decodable, Identifiable {
    var type: String?
    var severity: String?
    var title: String?
    var summary: String?

    var id: String { "\(type ?? "")-\(severity ?? "")-\(title ?? "")" }
}

struct StatusPayload: Decodable {
    var summary: String?
    var activeNow: [MemoryWrite]?
    var recentActivity: [MemoryWrite]?
    var recentDecisions: [MemoryWrite]?

    enum CodingKeys: String, CodingKey {
        case summary
        case activeNow = "active_now"
        case recentActivity = "recent_activity"
        case recentDecisions = "recent_decisions"
    }
}

struct WorkflowPayload: Decodable {
    var status: String?
    var coverage: String?
    var complete: Bool?
    var message: String?
    var nextSteps: [String]?

    enum CodingKeys: String, CodingKey {
        case status
        case coverage
        case complete
        case message
        case nextSteps = "next_steps"
    }
}

struct LaunchAgentStatus: Decodable {
    var label: String?
    var path: String?
    var installed: Bool?
    var loaded: Bool?
    var programArguments: [String]?

    enum CodingKeys: String, CodingKey {
        case label
        case path
        case installed
        case loaded
        case programArguments = "program_arguments"
    }
}

struct InstructionStatusPayload: Decodable {
    var targets: [InstructionTarget]?
    var workflow: WorkflowPayload?
    var dryRun: Bool?

    enum CodingKeys: String, CodingKey {
        case targets
        case workflow
        case dryRun = "dry_run"
    }
}

struct InstructionTarget: Decodable, Identifiable {
    var agent: String?
    var scope: String?
    var path: String?
    var description: String?
    var state: String?
    var action: String?
    var changed: Bool?
    var dryRun: Bool?

    var id: String {
        "\(agent ?? "agent")-\(scope ?? "scope")-\(path ?? "")"
    }

    enum CodingKeys: String, CodingKey {
        case agent
        case scope
        case path
        case description
        case state
        case action
        case changed
        case dryRun = "dry_run"
    }
}

struct SetupStatusPayload: Decodable {
    var pathRepair: SetupPathRepairPayload?
    var instructions: InstructionStatusPayload?
    var menubar: SetupMenubarPayload?
    var doctor: DoctorStatusPayload?
    var workflow: WorkflowPayload?

    enum CodingKeys: String, CodingKey {
        case pathRepair = "path_repair"
        case instructions
        case menubar
        case doctor
        case workflow
    }
}

struct SetupPathRepairPayload: Decodable {
    var ok: Bool?
    var skipped: Bool?
    var repaired: Bool?
    var repairAvailable: Bool?
    var reason: String?
    var error: String?
    var checkBefore: DoctorCheckPayload?
    var checkAfter: DoctorCheckPayload?

    enum CodingKeys: String, CodingKey {
        case ok
        case skipped
        case repaired
        case repairAvailable = "repair_available"
        case reason
        case error
        case checkBefore = "check_before"
        case checkAfter = "check_after"
    }
}

struct SetupMenubarPayload: Decodable {
    var supported: Bool?
    var skipped: Bool?
    var installed: Bool?
    var loaded: Bool?
    var reason: String?
    var error: String?
    var appBundleCurrent: Bool?
    var launchAgentCurrent: Bool?
    var status: LaunchAgentStatus?

    enum CodingKeys: String, CodingKey {
        case supported
        case skipped
        case installed
        case loaded
        case reason
        case error
        case appBundleCurrent = "app_bundle_current"
        case launchAgentCurrent = "launch_agent_current"
        case status
    }
}

struct DoctorStatusPayload: Decodable {
    var ok: Bool?
    var checks: [DoctorCheckPayload]?
}

struct DoctorCheckPayload: Decodable {
    var name: String?
    var required: Bool?
    var ok: Bool?
    var path: String?
    var error: String?
    var legacyWrapper: Bool?
    var standaloneWrapper: Bool?
    var packageEntrypoint: Bool?

    enum CodingKeys: String, CodingKey {
        case name
        case required
        case ok
        case path
        case error
        case legacyWrapper = "legacy_wrapper"
        case standaloneWrapper = "standalone_wrapper"
        case packageEntrypoint = "package_entrypoint"
    }
}

struct SetupHealthIssue: Identifiable, Equatable {
    let id: String
    let title: String
    let detail: String
    let systemImage: String
}
