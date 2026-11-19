// swift-tools-version: 6.2
import PackageDescription

let package = Package(
    name: "IAERPDemo",
    platforms: [.iOS("26.0"), .macOS("26.0")],
    products: [
        .library(name: "IAERPDemo", targets: ["IAERPDemo"]),
        .library(name: "IAERPClient", targets: ["IAERPClient"]),
        .library(name: "IAERPIdentity", targets: ["IAERPIdentity"]),
    ],
    dependencies: [
        .package(url: "https://github.com/openid/AppAuth-iOS.git", revision: "a972daac82d449d58ab119e91c68153e29ddac33"),
    ],
    targets: [
        .target(name: "IAERPDemo"),
        .testTarget(name: "IAERPDemoTests", dependencies: ["IAERPDemo"]),
        .target(name: "IAERPClient", resources: [.copy("Resources/BTOBTestInvoice")]),
        .testTarget(name: "IAERPClientTests", dependencies: ["IAERPClient"]),
        .target(name: "IAERPIdentity", dependencies: [
            .product(name: "AppAuth", package: "AppAuth-iOS", condition: .when(platforms: [.iOS])),
        ]),
        .testTarget(name: "IAERPIdentityTests", dependencies: ["IAERPIdentity"]),
    ],
    swiftLanguageModes: [.v6]
)
