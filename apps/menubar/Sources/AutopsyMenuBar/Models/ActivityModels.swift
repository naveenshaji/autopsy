import Foundation

struct ActivityPayload: Decodable {
    var workspace: WorkspacePayload?
    var activity: ActivityFeed?
    var status: StatusPayload?
    var workflow: WorkflowPayload?
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
}
