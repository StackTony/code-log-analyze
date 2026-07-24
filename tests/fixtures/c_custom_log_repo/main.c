/* 自定义日志函数 + 调用 */
void app_log_error(const char* msg);
void app_log_debug(const char* msg);

void handle(int x) {
    app_log_error("failed");
    app_log_debug("detail");
}