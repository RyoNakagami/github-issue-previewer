---
author: "Ryo Nakagami"
date-modified: "2025-10-23"
---

# Version Policy

The version management of `<default-package-name-for-rename>` follows [Semantic Versioning](https://semver.org/).  
Each release number is structured as `MAJOR.MINOR.PATCH`.

## Major Release

- Major releases are issued when breaking changes that are **not backward compatible** occur.
- Changes included in a major release are documented in the **Release Notes**.
- Deprecations that remove methods or attributes are applied **only** in major releases.

## Minor Release

- Minor releases include substantial bug fixes or **new features** added without breaking backward compatibility (e.g., adding new methods).
- Deprecation announcements are made during minor releases (they are **not introduced** in patch releases).

Deprecation announcements provide guidance on the following points:

- Recommended **alternative solutions**  
- Version in which the **deprecation will be enforced**

For example, if a feature is deprecated in `<default-package-name-for-rename>` version `1.2.0`, it will continue to operate with warnings across all `1.x` releases. The deprecated feature will be removed in the next **major release** (`2.0.0`).

## Patch Release

- Patch releases are issued for **backward-compatible bug fixes**.  
- Backward compatibility means that upgrading the package version does **not break** any previously written code.

## Creating Git Tags for Releases

To mark releases in your Git repository, you should create **annotated tags** following semantic versioning:

1. **Create a tag for the release:**

    ```bash
    git tag -a v1.2.0 -m "Release version 1.2.0: [short description]"
    ```

2. **Push the tag to the remote repository:**

    ```bash
    git push origin v1.2.0
    ```

3. **Optional: Push all tags at once:**

    ```bash
    git push --tags
    ```

### Best practices

- Use `vMAJOR.MINOR.PATCH` format (e.g., `v1.2.0`).
- Include a short description in the tag message summarizing the release changes.
- Always tag the commit that corresponds to the exact state of the release.

## References

- [Semantic Versioning](https://semver.org/)
- [Python Package Versioning Guide by Regmonkeys](https://ryonakagami.github.io/python-statisticalpackage-techniques/posts/python-packaging-guide/versioning.html)
