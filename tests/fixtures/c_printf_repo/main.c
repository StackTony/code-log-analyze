#include <stdio.h>

int do_work(int x) {
    printf("processing %d\n", x);
    fprintf(stderr, "error on %d\n", x);
    return x * 2;
}