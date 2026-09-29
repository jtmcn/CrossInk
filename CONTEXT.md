# Personal Builds (jtmcn forks)

Language for building, releasing, and debugging personal X4 Pro firmware from the jtmcn forks of CrossInk and freeink-sdk, which are operated together as one project. Terms here exist only on the forks.

## Repositories and branches

**Upstream**:
The original project a fork tracks: uxjulia/CrossInk for CrossInk, Free-Ink/freeink-sdk for the SDK.
_Avoid_: origin (it names upstream in the SDK but the fork in CrossInk)

**Fork**:
The jtmcn copy of a repository, where integration branches, topics, and personal releases live.
_Avoid_: origin, fork remote

**Integration branch**:
The fork branch that only advances by merging and that personal builds come from; CrossInk's is `personal`, the SDK's is `crossink`.
_Avoid_: "the crossink branch" without naming the repository, stack

**Topic**:
One change, kept upstream-PR-ready on its own branch in one repository.
_Avoid_: feature branch, patch

**Paired topic**:
An SDK topic together with the CrossInk topic whose pin points at that SDK topic.

**Retired topic**:
A topic whose upstream PR has merged and whose merge the integration branch already contains.

**Superseded topic**:
A topic whose effect upstream delivered by other means, so the fork no longer needs it; unlike a retired topic, only a person can declare it.
_Avoid_: closed topic, dead topic

**Pin**:
The SDK commit that a CrossInk commit records as its submodule.
_Avoid_: gitlink bump, SDK SHA

**Fork delta**:
What an integration branch carries beyond upstream, counted from their merge base.

**Sync**:
Catching both integration branches up with their upstreams and repinning the SDK.
_Avoid_: rebase, update

## Builds and releases

**Personal build**:
Firmware built from the integration branches for daily reading on the X4 Pro, updating over the air from the fork.
_Avoid_: daily build, custom firmware

**Debug build**:
A personal build that waits for a serial connection at boot for desk debugging, and still updates over the air from the fork.
_Avoid_: test build, dev build

**Upstream debug build**:
Upstream's debug firmware, which updates over the air from upstream instead of the fork, so installing an update leaves the personal release line.
_Avoid_: debug build (unqualified)

**Personal release**:
A published fork release carrying one personal build, versioned `v<base>.<N>`.
_Avoid_: tag, OTA build

**Base version**:
The upstream CrossInk version a personal release is built on, the `<base>` in `v<base>.<N>`.

**Build number**:
The `<N>` in `v<base>.<N>`; it grows with every personal release so each one is newer to the reader's update check.

**Symbols**:
The debug-information file matching one personal build, published alongside it so its crashes can be decoded.
_Avoid_: ELF (as a user-facing term), debug build

## On-device evidence

**Crash report**:
The file the reader writes after a panic, with the panic reason, backtrace, and recent log lines.
_Avoid_: the logs

**SD log**:
The rotating log file a personal build appends to on the SD card during normal use.
_Avoid_: the logs, serial log

**RTC ring**:
The last few log lines, held in memory that survives a reset but not power loss.

**Reset tail**:
The RTC ring copied into the SD log after a watchdog, panic, or brownout reset.

**Network boot**:
A silent restart into a minimal boot that opens one network screen, such as Check for Updates.
