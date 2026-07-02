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

    enum CodingKeys: String, CodingKey {
        case service
        case apiVersion = "api_version"
        case features
        case capabilities
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
    var canReadAuditIntegrity: Bool?
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
    var expiredTokensCount: Int?
    var revokedTokensCount: Int?
    var disabledTokensCount: Int?
    var roleCounts: [String: Int]?
    var tokenRoleCounts: [String: Int]?
    var auditIntegrity: SharedServerAuditIntegrityPayload?
    var usersError: String?
    var grantsError: String?
    var tokensError: String?
    var auditIntegrityError: String?

    enum CodingKeys: String, CodingKey {
        case repo
        case canListUsers = "can_list_users"
        case canListGrants = "can_list_grants"
        case canListTokens = "can_list_tokens"
        case canReadAuditIntegrity = "can_read_audit_integrity"
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
        case expiredTokensCount = "expired_tokens_count"
        case revokedTokensCount = "revoked_tokens_count"
        case disabledTokensCount = "disabled_tokens_count"
        case roleCounts = "role_counts"
        case tokenRoleCounts = "token_role_counts"
        case auditIntegrity = "audit_integrity"
        case usersError = "users_error"
        case grantsError = "grants_error"
        case tokensError = "tokens_error"
        case auditIntegrityError = "audit_integrity_error"
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
