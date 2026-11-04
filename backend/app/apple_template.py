"""Starter Swift package of an Apple project: compiles and passes its test, holds no key or token."""

import re

SWIFT_TOOLS_VERSION = "5.9"
FALLBACK_MODULE_NAME = "App"
IOS_MINIMUM_VERSION = "17"

APPLE_GITIGNORE = """.build/
.swiftpm/
xcuserdata/
DerivedData/
*.xcodeproj/project.xcworkspace/
"""


def module_name(project_name: str) -> str:
    """A valid Swift module name drawn from the project name (letters and digits, not starting with a digit)."""
    words = re.findall(r"[A-Za-z0-9]+", project_name)
    name = "".join(word[:1].upper() + word[1:] for word in words)
    if not name or name[0].isdigit():
        return FALLBACK_MODULE_NAME
    return name


def starter_files(project_name: str) -> dict[str, str]:
    """Path to content of the starter package: manifest, one source and one passing test."""
    module = module_name(project_name)
    return {
        "Package.swift": f"""// swift-tools-version:{SWIFT_TOOLS_VERSION}
import PackageDescription

let package = Package(
    name: "{module}",
    platforms: [.iOS(.v{IOS_MINIMUM_VERSION})],
    products: [.library(name: "{module}", targets: ["{module}"])],
    targets: [
        .target(name: "{module}"),
        .testTarget(name: "{module}Tests", dependencies: ["{module}"]),
    ]
)
""",
        f"Sources/{module}/{module}.swift": """public struct Greeter {
    public init() {}

    public func greeting() -> String {
        "Hello"
    }
}
""",
        f"Tests/{module}Tests/{module}Tests.swift": f"""import XCTest
@testable import {module}

final class {module}Tests: XCTestCase {{
    func testGreeting() {{
        XCTAssertEqual(Greeter().greeting(), "Hello")
    }}
}}
""",
    }
