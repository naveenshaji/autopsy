// swift-tools-version: 5.9

import PackageDescription

let package = Package(
    name: "AutopsyMenuBar",
    platforms: [
        .macOS(.v13)
    ],
    products: [
        .executable(name: "AutopsyMenuBar", targets: ["AutopsyMenuBar"])
    ],
    targets: [
        .executableTarget(name: "AutopsyMenuBar")
    ]
)
