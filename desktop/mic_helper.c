/* prompta-mic: runs the Whisper dictation worker as its own microphone client.
 *
 * Prompta's launcher becomes the system Python, whose bundle has no NSMicrophoneUsageDescription, so macOS
 * silently hands it silence and never asks. This helper carries its own Info.plist (embedded at build time)
 * with that description. It re-launches itself "disclaimed", which makes it the process macOS asks about,
 * then starts the worker as its child. stdin/stdout/stderr pass straight through to Prompta.
 *
 * Usage: prompta-mic <python> <script> [args...]
 */
#include <mach-o/dyld.h>
#include <signal.h>
#include <spawn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include <unistd.h>

extern char **environ;
/* Exported by libSystem; the documented way for helpers to become their own privacy-responsible process. */
extern int responsibility_spawnattrs_setdisclaim(posix_spawnattr_t *attrs, int disclaim);

static pid_t child = 0;

static void forward(int sig) {
    if (child > 0) kill(child, sig);
}

static int run(const char *path, char *const argv[], int disclaim) {
    posix_spawnattr_t attrs;
    posix_spawnattr_init(&attrs);
    if (disclaim) responsibility_spawnattrs_setdisclaim(&attrs, 1);
    int error = posix_spawn(&child, path, NULL, &attrs, argv, environ);
    posix_spawnattr_destroy(&attrs);
    if (error) {
        fprintf(stderr, "prompta-mic: cannot start %s (%s)\n", path, strerror(error));
        return 127;
    }
    signal(SIGTERM, forward);
    signal(SIGINT, forward);
    int status = 0;
    while (waitpid(child, &status, 0) < 0) {
    }
    return WIFEXITED(status) ? WEXITSTATUS(status) : 1;
}

int main(int argc, char **argv) {
    int disclaimed = argc > 1 && strcmp(argv[1], "--disclaimed") == 0;
    int first = disclaimed ? 2 : 1;
    if (argc - first < 2) {
        fprintf(stderr, "usage: prompta-mic <python> <script> [args...]\n");
        return 2;
    }
    if (!disclaimed) {
        char self[4096];
        uint32_t size = sizeof self;
        if (_NSGetExecutablePath(self, &size) != 0) return 1;
        char **args = calloc((size_t)argc + 2, sizeof *args);
        if (!args) return 1;
        args[0] = self;
        args[1] = "--disclaimed";
        for (int i = 1; i < argc; i++) args[i + 1] = argv[i];
        return run(self, args, 1);
    }
    return run(argv[first], &argv[first], 0);
}
