#include <unistd.h>
#include <stdlib.h>
#include <stdio.h>

int main(int argc, char *argv[]) {
    if (setuid(0) != 0) {
        perror("setuid failed");
        return 1;
    }
    execv("/usr/local/bin/nvidia-oc-bin", argv);
    perror("execv failed");
    return 1;
}
