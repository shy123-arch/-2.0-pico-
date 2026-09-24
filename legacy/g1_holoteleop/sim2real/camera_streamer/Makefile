CXX ?= g++
PKG_CONFIG ?= pkg-config

TARGET := holoteleop_camera_streamer
BUILD_DIR := build
SRC := $(wildcard src/*.cpp)
OBJ := $(patsubst src/%.cpp,$(BUILD_DIR)/%.o,$(SRC))

PKGS := gstreamer-1.0 gstreamer-app-1.0
GST_CFLAGS := $(shell $(PKG_CONFIG) --cflags $(PKGS) 2>/dev/null)
GST_LDFLAGS := $(shell $(PKG_CONFIG) --libs $(PKGS) 2>/dev/null)
CXXFLAGS ?= -O3 -DNDEBUG -std=c++17 -Wall -Wextra -Wpedantic
CXXFLAGS += -Iinclude $(GST_CFLAGS)
LDFLAGS += $(GST_LDFLAGS) -pthread

.PHONY: all clean

all: $(TARGET)

check-deps:
	@$(PKG_CONFIG) --exists $(PKGS) || ( \
		echo "Missing pkg-config deps: $(PKGS)"; \
		echo "Install gstreamer development packages on the build machine."; \
		exit 1; \
	)

$(TARGET): check-deps $(OBJ)
	$(CXX) $(OBJ) -o $@ $(LDFLAGS)

$(BUILD_DIR)/%.o: src/%.cpp
	@mkdir -p $(BUILD_DIR)
	$(CXX) $(CXXFLAGS) -c $< -o $@

$(OBJ): | check-deps

clean:
	rm -rf $(BUILD_DIR) $(TARGET)
