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
    var idempotencyRecordRetentionDays: Int?
    var idempotencyPendingTimeoutSeconds: Int?

    enum CodingKeys: String, CodingKey {
        case defaultInviteTokenExpirationDays = "default_invite_token_expiration_days"
        case idempotencyRecordRetentionDays = "idempotency_record_retention_days"
        case idempotencyPendingTimeoutSeconds = "idempotency_pending_timeout_seconds"
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
    var auditWindowSince: String?
    var auditWindowUntil: String?
    var canListUsers: Bool?
    var canListGrants: Bool?
    var canListTokens: Bool?
    var canListPolicies: Bool?
    var canReadPolicy: Bool?
    var canReadAuditIntegrity: Bool?
    var canReadRepoPolicyConflicts: Bool?
    var canReadRelationPolicyConflicts: Bool?
    var canReadMemoryPolicyConflicts: Bool?
    var canReadMemoryVersionConflicts: Bool?
    var canReadIdempotencyReplays: Bool?
    var canReadIdempotencyConflicts: Bool?
    var canReadInviteExpirationSummary: Bool?
    var canReadAuditReaderSummary: Bool?
    var canReadSharedReadSummary: Bool?
    var canReadStorageStatus: Bool?
    var canUseAdminExportSnapshot: Bool?
    var canUseAdminExportSnapshotValidation: Bool?
    var canUseAdminExportSnapshotRestorePlan: Bool?
    var canUseAdminExportSnapshotRestorePlanDigest: Bool?
    var canUseAdminExportSnapshotRestoreApply: Bool?
    var canUseAdminExportSnapshotManifest: Bool?
    var canUseTokenInventoryFingerprints: Bool?
    var canUseIdempotencyKeys: Bool?
    var canUseIdempotencyRecordRetention: Bool?
    var idempotencyRecordRetentionDays: Int?
    var idempotencyPendingTimeoutSeconds: Int?
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
    var disabledMemoryPolicyCount: Int?
    var policyInventoryRepoFilterPresent: Bool?
    var effectivePolicyRepo: String?
    var effectivePolicyInheritedFrom: String?
    var effectivePolicyVersionNS: String?
    var effectivePolicyFingerprint: String?
    var effectivePolicyRelationLabelCount: Int?
    var effectivePolicyMemoryKindCount: Int?
    var effectivePolicyMinFactRating: Double?
    var effectivePolicySharedRelationsAllowed: Bool?
    var effectivePolicyPersonalRelationsAllowed: Bool?
    var effectivePolicyMemoryWritesAllowed: Bool?
    var effectivePolicyConstrained: Bool?
    var roleCounts: [String: Int]?
    var tokenRoleCounts: [String: Int]?
    var auditIntegrity: SharedServerAuditIntegrityPayload?
    var repoPolicyConflictCount: Int?
    var repoPolicyConflictModeCounts: [String: Int]?
    var repoPolicyConflictReasonCounts: [String: Int]?
    var latestRepoPolicyConflictAt: String?
    var relationPolicyConflictCount: Int?
    var relationPolicyConflictScopeCounts: [String: Int]?
    var relationPolicyConflictCurrentReasonCounts: [String: Int]?
    var latestRelationPolicyConflictAt: String?
    var memoryPolicyConflictCount: Int?
    var memoryPolicyConflictKindCounts: [String: Int]?
    var memoryPolicyConflictCurrentReasonCounts: [String: Int]?
    var latestMemoryPolicyConflictAt: String?
    var memoryVersionConflictCount: Int?
    var memoryVersionConflictModeCounts: [String: Int]?
    var memoryVersionConflictReasonCounts: [String: Int]?
    var memoryVersionConflictKindCounts: [String: Int]?
    var memoryVersionConflictCurrentArchivedCounts: [String: Int]?
    var latestMemoryVersionConflictAt: String?
    var idempotencyReplayCount: Int?
    var idempotencyReplayModeCounts: [String: Int]?
    var latestIdempotencyReplayAt: String?
    var idempotencyConflictCount: Int?
    var idempotencyConflictModeCounts: [String: Int]?
    var idempotencyConflictReasonCounts: [String: Int]?
    var latestIdempotencyConflictAt: String?
    var inviteExpirationAuditCount: Int?
    var inviteExpirationDefaultedCount: Int?
    var inviteExpirationExplicitCount: Int?
    var inviteExpirationUnknownCount: Int?
    var latestInviteExpirationAuditAt: String?
    var auditReaderSummarySource: String?
    var auditReaderAuditCount: Int?
    var auditReaderScopedTokenCount: Int?
    var auditReaderDirectTokenCount: Int?
    var auditReaderUnknownTokenScopeCount: Int?
    var auditReaderScopeMatchCounts: [String: Int]?
    var auditReaderScopeGraphCounts: [String: Int]?
    var auditReaderScopeRepoCounts: [String: Int]?
    var auditReaderScopeRoleCounts: [String: Int]?
    var latestAuditReaderAuditAt: String?
    var sharedReadSummarySource: String?
    var sharedReadAuditCount: Int?
    var sharedReadScopedTokenCount: Int?
    var sharedReadDirectTokenCount: Int?
    var sharedReadUnknownTokenScopeCount: Int?
    var sharedReadScopeMatchCounts: [String: Int]?
    var sharedReadScopeGraphCounts: [String: Int]?
    var sharedReadScopeRepoCounts: [String: Int]?
    var sharedReadScopeRoleCounts: [String: Int]?
    var latestSharedReadAuditAt: String?
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
    var storageIdempotencyRecordCount: Int?
    var storagePendingIdempotencyRecordCount: Int?
    var storageCompletedIdempotencyRecordCount: Int?
    var storageAuditEventCount: Int?
    var storageOldestIdempotencyRecordCreatedAt: String?
    var storageOldestPendingIdempotencyRecordCreatedAt: String?
    var storageOldestCompletedIdempotencyAt: String?
    var storageIdempotencyCompletedRetentionDays: Int?
    var storageIdempotencyPendingTimeoutSeconds: Int?
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
    var repoPolicyConflictsError: String?
    var relationPolicyConflictsError: String?
    var memoryPolicyConflictsError: String?
    var memoryVersionConflictsError: String?
    var idempotencyReplaysError: String?
    var idempotencyConflictsError: String?
    var inviteExpirationSummaryError: String?
    var auditReaderSummaryError: String?
    var sharedReadSummaryError: String?
    var storageStatusError: String?

    enum CodingKeys: String, CodingKey {
        case repo
        case auditWindowSince = "audit_window_since"
        case auditWindowUntil = "audit_window_until"
        case canListUsers = "can_list_users"
        case canListGrants = "can_list_grants"
        case canListTokens = "can_list_tokens"
        case canListPolicies = "can_list_policies"
        case canReadPolicy = "can_read_policy"
        case canReadAuditIntegrity = "can_read_audit_integrity"
        case canReadRepoPolicyConflicts = "can_read_repo_policy_conflicts"
        case canReadRelationPolicyConflicts = "can_read_relation_policy_conflicts"
        case canReadMemoryPolicyConflicts = "can_read_memory_policy_conflicts"
        case canReadMemoryVersionConflicts = "can_read_memory_version_conflicts"
        case canReadIdempotencyReplays = "can_read_idempotency_replays"
        case canReadIdempotencyConflicts = "can_read_idempotency_conflicts"
        case canReadInviteExpirationSummary = "can_read_invite_expiration_summary"
        case canReadAuditReaderSummary = "can_read_audit_reader_summary"
        case canReadSharedReadSummary = "can_read_shared_read_summary"
        case canReadStorageStatus = "can_read_storage_status"
        case canUseAdminExportSnapshot = "can_use_admin_export_snapshot"
        case canUseAdminExportSnapshotValidation = "can_use_admin_export_snapshot_validation"
        case canUseAdminExportSnapshotRestorePlan = "can_use_admin_export_snapshot_restore_plan"
        case canUseAdminExportSnapshotRestorePlanDigest = "can_use_admin_export_snapshot_restore_plan_digest"
        case canUseAdminExportSnapshotRestoreApply = "can_use_admin_export_snapshot_restore_apply"
        case canUseAdminExportSnapshotManifest = "can_use_admin_export_snapshot_manifest"
        case canUseTokenInventoryFingerprints = "can_use_token_inventory_fingerprints"
        case canUseIdempotencyKeys = "can_use_idempotency_keys"
        case canUseIdempotencyRecordRetention = "can_use_idempotency_record_retention"
        case idempotencyRecordRetentionDays = "idempotency_record_retention_days"
        case idempotencyPendingTimeoutSeconds = "idempotency_pending_timeout_seconds"
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
        case disabledMemoryPolicyCount = "disabled_memory_policy_count"
        case policyInventoryRepoFilterPresent = "policy_inventory_repo_filter_present"
        case effectivePolicyRepo = "effective_policy_repo"
        case effectivePolicyInheritedFrom = "effective_policy_inherited_from"
        case effectivePolicyVersionNS = "effective_policy_version_ns"
        case effectivePolicyFingerprint = "effective_policy_fingerprint"
        case effectivePolicyRelationLabelCount = "effective_policy_relation_label_count"
        case effectivePolicyMemoryKindCount = "effective_policy_memory_kind_count"
        case effectivePolicyMinFactRating = "effective_policy_min_fact_rating"
        case effectivePolicySharedRelationsAllowed = "effective_policy_shared_relations_allowed"
        case effectivePolicyPersonalRelationsAllowed = "effective_policy_personal_relations_allowed"
        case effectivePolicyMemoryWritesAllowed = "effective_policy_memory_writes_allowed"
        case effectivePolicyConstrained = "effective_policy_constrained"
        case roleCounts = "role_counts"
        case tokenRoleCounts = "token_role_counts"
        case auditIntegrity = "audit_integrity"
        case repoPolicyConflictCount = "repo_policy_conflict_count"
        case repoPolicyConflictModeCounts = "repo_policy_conflict_mode_counts"
        case repoPolicyConflictReasonCounts = "repo_policy_conflict_reason_counts"
        case latestRepoPolicyConflictAt = "latest_repo_policy_conflict_at"
        case relationPolicyConflictCount = "relation_policy_conflict_count"
        case relationPolicyConflictScopeCounts = "relation_policy_conflict_scope_counts"
        case relationPolicyConflictCurrentReasonCounts = "relation_policy_conflict_current_reason_counts"
        case latestRelationPolicyConflictAt = "latest_relation_policy_conflict_at"
        case memoryPolicyConflictCount = "memory_policy_conflict_count"
        case memoryPolicyConflictKindCounts = "memory_policy_conflict_kind_counts"
        case memoryPolicyConflictCurrentReasonCounts = "memory_policy_conflict_current_reason_counts"
        case latestMemoryPolicyConflictAt = "latest_memory_policy_conflict_at"
        case memoryVersionConflictCount = "memory_version_conflict_count"
        case memoryVersionConflictModeCounts = "memory_version_conflict_mode_counts"
        case memoryVersionConflictReasonCounts = "memory_version_conflict_reason_counts"
        case memoryVersionConflictKindCounts = "memory_version_conflict_kind_counts"
        case memoryVersionConflictCurrentArchivedCounts = "memory_version_conflict_current_archived_counts"
        case latestMemoryVersionConflictAt = "latest_memory_version_conflict_at"
        case idempotencyReplayCount = "idempotency_replay_count"
        case idempotencyReplayModeCounts = "idempotency_replay_mode_counts"
        case latestIdempotencyReplayAt = "latest_idempotency_replay_at"
        case idempotencyConflictCount = "idempotency_conflict_count"
        case idempotencyConflictModeCounts = "idempotency_conflict_mode_counts"
        case idempotencyConflictReasonCounts = "idempotency_conflict_reason_counts"
        case latestIdempotencyConflictAt = "latest_idempotency_conflict_at"
        case inviteExpirationAuditCount = "invite_expiration_audit_count"
        case inviteExpirationDefaultedCount = "invite_expiration_defaulted_count"
        case inviteExpirationExplicitCount = "invite_expiration_explicit_count"
        case inviteExpirationUnknownCount = "invite_expiration_unknown_count"
        case latestInviteExpirationAuditAt = "latest_invite_expiration_audit_at"
        case auditReaderSummarySource = "audit_reader_summary_source"
        case auditReaderAuditCount = "audit_reader_audit_count"
        case auditReaderScopedTokenCount = "audit_reader_scoped_token_count"
        case auditReaderDirectTokenCount = "audit_reader_direct_token_count"
        case auditReaderUnknownTokenScopeCount = "audit_reader_unknown_token_scope_count"
        case auditReaderScopeMatchCounts = "audit_reader_scope_match_counts"
        case auditReaderScopeGraphCounts = "audit_reader_scope_graph_counts"
        case auditReaderScopeRepoCounts = "audit_reader_scope_repo_counts"
        case auditReaderScopeRoleCounts = "audit_reader_scope_role_counts"
        case latestAuditReaderAuditAt = "latest_audit_reader_audit_at"
        case sharedReadSummarySource = "shared_read_summary_source"
        case sharedReadAuditCount = "shared_read_audit_count"
        case sharedReadScopedTokenCount = "shared_read_scoped_token_count"
        case sharedReadDirectTokenCount = "shared_read_direct_token_count"
        case sharedReadUnknownTokenScopeCount = "shared_read_unknown_token_scope_count"
        case sharedReadScopeMatchCounts = "shared_read_scope_match_counts"
        case sharedReadScopeGraphCounts = "shared_read_scope_graph_counts"
        case sharedReadScopeRepoCounts = "shared_read_scope_repo_counts"
        case sharedReadScopeRoleCounts = "shared_read_scope_role_counts"
        case latestSharedReadAuditAt = "latest_shared_read_audit_at"
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
        case storageIdempotencyRecordCount = "storage_idempotency_record_count"
        case storagePendingIdempotencyRecordCount = "storage_pending_idempotency_record_count"
        case storageCompletedIdempotencyRecordCount = "storage_completed_idempotency_record_count"
        case storageAuditEventCount = "storage_audit_event_count"
        case storageOldestIdempotencyRecordCreatedAt = "storage_oldest_idempotency_record_created_at"
        case storageOldestPendingIdempotencyRecordCreatedAt = "storage_oldest_pending_idempotency_record_created_at"
        case storageOldestCompletedIdempotencyAt = "storage_oldest_completed_idempotency_at"
        case storageIdempotencyCompletedRetentionDays = "storage_idempotency_completed_retention_days"
        case storageIdempotencyPendingTimeoutSeconds = "storage_idempotency_pending_timeout_seconds"
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
        case repoPolicyConflictsError = "repo_policy_conflicts_error"
        case relationPolicyConflictsError = "relation_policy_conflicts_error"
        case memoryPolicyConflictsError = "memory_policy_conflicts_error"
        case memoryVersionConflictsError = "memory_version_conflicts_error"
        case idempotencyReplaysError = "idempotency_replays_error"
        case idempotencyConflictsError = "idempotency_conflicts_error"
        case inviteExpirationSummaryError = "invite_expiration_summary_error"
        case auditReaderSummaryError = "audit_reader_summary_error"
        case sharedReadSummaryError = "shared_read_summary_error"
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
