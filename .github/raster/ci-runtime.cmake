# Add fork-specific attribution without editing upstream application sources.
function(qms_ci_runtime_notices)
    target_sources(qmapshack PRIVATE "${CMAKE_CURRENT_FUNCTION_LIST_DIR}/runtime_notices.cpp")
endfunction()
cmake_language(DEFER CALL qms_ci_runtime_notices)

