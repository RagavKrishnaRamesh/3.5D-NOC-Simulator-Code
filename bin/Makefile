##### LIBRARIES CONFIGURATION #####
# Defaults to local installs under ./bin; override by exporting SYSTEMC_HOME/YAML_HOME
CURDIR       := $(abspath .)
SYSTEMC_HOME ?= $(CURDIR)/systemc/2.3.4
YAML_HOME    ?= $(CURDIR)/yaml-cpp
SYSTEMC_INC  ?= -I"$(SYSTEMC_HOME)/include"
YAML_INC     ?= -I"$(YAML_HOME)/include"
SYSTEMC_LIBS := $(shell if [ -d "$(SYSTEMC_HOME)/lib64" ]; then echo "$(SYSTEMC_HOME)/lib64"; else echo "$(SYSTEMC_HOME)/lib"; fi)
YAML_LIBDIR  := $(shell if [ -d "$(YAML_HOME)/lib64" ]; then echo "$(YAML_HOME)/lib64"; else echo "$(YAML_HOME)/lib"; fi)

SYSTEMC := $(SYSTEMC_HOME)
YAML    := $(YAML_HOME)


##### DIRECTORIES #####

SRCDIR  := ../src
SUBDIRS := $(filter %/,$(wildcard $(SRCDIR)/*/))
OBJDIR  := ./build

SRCS := $(wildcard $(SRCDIR)/*.cpp) $(wildcard $(addsuffix *.cpp,$(SUBDIRS)))
OBJS := $(subst $(SRCDIR),$(OBJDIR),$(SRCS:.cpp=.o))

MODULE := noxim


##### COMPILER OPTIONS #####

CXX       := g++
ifdef DEBUG
OPT_DEBUG := -g -DDEBUG -DATOMIC_FLOW_CONTROL_CHECK -DDEBUG_VC_UTILIZATION
else
OPT       := -O3
endif
OTHER     := -Wall -DSC_NO_WRITE_CHECK --std=c++14
CXXFLAGS  := $(OPT) $(OTHER) $(OPT_DEBUG)

INCDIR := -I"$(SRCDIR)" $(SYSTEMC_INC) $(YAML_INC)
//LIBDIR := -L$(SRCDIR) $(addprefix -L,$(SYSTEMC_LIBS)) -L$(YAML_LIBDIR) -Wl,-rpath,$(SYSTEMC_LIBS)
LIBDIR := -L"$(SRCDIR)" -L"$(SYSTEMC_LIBS)" -L"$(YAML_LIBDIR)" -Wl,-rpath,"$(SYSTEMC_LIBS)" -Wl,-rpath,"$(YAML_LIBDIR)"
LIBS := -lsystemc -lm -lyaml-cpp 

SPACE := $(subst ,, )
VPATH := $(SRCDIR):$(subst $(SPACE),:,$(SUBDIRS))

##### RULES #####

$(MODULE): $(OBJS)
	$(CXX) $(LIBDIR) $^ $(LIBS) -o $@ 2>&1 | c++filt

$(OBJDIR)/%.o: %.cpp
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) $(INCDIR) -c $< -o $@

clean:
	rm -f $(OBJS) $(MODULE) *~

depend: 
	makedepend $(SRCS) -Y -f- 2>/dev/null | sed 's_$(SRCDIR)_$(OBJDIR)_' > Makefile.deps

-include Makefile.deps
