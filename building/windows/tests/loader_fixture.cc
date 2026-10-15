#include <scene/rdl2/Macros.h>
extern "C" int dependency_value();
extern "C" RDL2_DSO_EXPORT int fixture_value() { return dependency_value() + 1; }
