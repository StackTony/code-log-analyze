#include <syslog.h>

void worker(int level) {
    syslog(LOG_INFO, "started level=%d", level);
    syslog(LOG_ERR, "error level=%d", level);
}