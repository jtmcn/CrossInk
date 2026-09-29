# Personal releases carry a fourth version segment

Personal releases are versioned `v<base>.<N>` (e.g. `v1.6.0.2`): the upstream base version plus a build number that grows with every release and restarts when the base changes. The reader's update check (`compareVersions` in `src/network/OtaUpdater.cpp`) only compares up to four numeric segments and ignores anything after the first non-digit, so the build number must be a numeric segment for each release to count as newer.

## Considered Options

- **Suffix (`v1.6.0-p2`)**: compares equal to `1.6.0`, so the reader never offers the update.
- **Bump the patch (`v1.6.1`)**: collides with upstream's next release, and a later rebase onto upstream 1.6.1 would not look newer than the personal 1.6.1.
- **Fourth segment (chosen)**: always newer within a base, and a new upstream base (`1.7.0.1`) outranks every build on the old one.

## Consequences

Builds that are not personal releases (local builds, debug builds) report build number 0, so the update check always offers the latest personal release back. Changing this scheme after readers have installed a `<base>.<N>` release risks their update check treating new releases as older.
