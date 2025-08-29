FROM --platform=linux/amd64 ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=Asia/Shanghai

# Update and install base packages
RUN apt-get update && apt-get install -y \
    wget \
    curl \
    git \
    sudo \
    tzdata \
    locales \
    software-properties-common \
    apt-transport-https \
    ca-certificates \
    gnupg \
    lsb-release \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Set locale
RUN locale-gen en_US.UTF-8
ENV LANG=en_US.UTF-8
ENV LANGUAGE=en_US:en
ENV LC_ALL=en_US.UTF-8

# Install Node.js (latest LTS version) and npm
RUN curl -fsSL https://deb.nodesource.com/setup_lts.x | bash - && \
    apt-get install -y nodejs && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* && \
    npm install -g npm@latest && \
    node --version && \
    npm --version

# Install im-platform-mcp globally
RUN npm install -g im-platform-mcp && \
    npm list -g im-platform-mcp

# Install desktop environment (XFCE4 - lightweight)
RUN apt-get update && apt-get install -y \
    xfce4 \
    xfce4-terminal \
    xfce4-goodies \
    dbus-x11 \
    x11-utils \
    x11-xserver-utils \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Install VNC server, SSH server and noVNC for web access
RUN apt-get update && apt-get install -y \
    tigervnc-standalone-server \
    tigervnc-common \
    novnc \
    websockify \
    supervisor \
    net-tools \
    gnome-keyring \
    libsecret-1-0 \
    libsecret-tools \
    openssh-server \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Install additional utilities and dependencies for Void
RUN apt-get update && apt-get install -y \
    libnss3 \
    libatk-bridge2.0-0 \
    libdrm2 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libxkbcommon0 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    libatspi2.0-0 \
    libgtk-3-0 \
    libxshmfence1 \
    libglu1-mesa \
    fonts-wqy-microhei \
    fonts-wqy-zenhei \
    fonts-noto-cjk \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Create user and configure SSH
RUN useradd -m -s /bin/bash void && \
    echo "void:void" | chpasswd && \
    usermod -aG sudo void && \
    echo "void ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers

# Configure SSH
RUN mkdir -p /var/run/sshd && \
    sed -i 's/#PermitRootLogin prohibit-password/PermitRootLogin yes/' /etc/ssh/sshd_config && \
    sed -i 's/#PasswordAuthentication yes/PasswordAuthentication yes/' /etc/ssh/sshd_config && \
    sed -i 's/UsePAM yes/UsePAM no/' /etc/ssh/sshd_config && \
    echo "void:void" | chpasswd

# Download and install Void (latest version from GitHub)
RUN apt-get update && apt-get install -y jq && \
    VOID_VERSION=$(curl -s https://api.github.com/repos/qinkee/binaries/releases/latest | jq -r '.tag_name') && \
    echo "Installing Void version: ${VOID_VERSION}" && \
    wget -O /tmp/void.deb "https://github.com/qinkee/binaries/releases/download/${VOID_VERSION}/void_${VOID_VERSION}_amd64.deb" && \
    apt-get install -y /tmp/void.deb || true && \
    apt-get install -f -y && \
    rm /tmp/void.deb && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Download and install IM components
RUN echo "Downloading and installing IM components..." && \
    wget -O /tmp/im-components.tar.gz https://aiim.service.thinkgs.cn/im-components/im-components.tar.gz && \
    mkdir -p /usr/share/void/resources/app/out/vs/code/electron-sandbox/workbench && \
    rm -rf /usr/share/void/resources/app/out/vs/code/electron-sandbox/workbench/im-components && \
    tar -xzf /tmp/im-components.tar.gz -C /usr/share/void/resources/app/out/vs/code/electron-sandbox/workbench/ && \
    rm /tmp/im-components.tar.gz && \
    echo "IM components installed successfully"

# Setup VNC - password will be set at runtime from environment variable
USER void
RUN mkdir -p /home/void/.vnc

# Create desktop entry for Void with Docker-specific fixes
RUN mkdir -p /home/void/.local/share/applications && \
    echo "[Desktop Entry]" > /home/void/.local/share/applications/void.desktop && \
    echo "Version=1.0" >> /home/void/.local/share/applications/void.desktop && \
    echo "Type=Application" >> /home/void/.local/share/applications/void.desktop && \
    echo "Name=Void Editor" >> /home/void/.local/share/applications/void.desktop && \
    echo "Comment=Code Editor based on VSCode" >> /home/void/.local/share/applications/void.desktop && \
    echo "Exec=/usr/share/void/void --password-store=basic --disable-gpu %F" >> /home/void/.local/share/applications/void.desktop && \
    echo "Icon=void" >> /home/void/.local/share/applications/void.desktop && \
    echo "Categories=Development;IDE;" >> /home/void/.local/share/applications/void.desktop && \
    echo "Terminal=false" >> /home/void/.local/share/applications/void.desktop && \
    echo "StartupNotify=true" >> /home/void/.local/share/applications/void.desktop

# Create Desktop shortcut
RUN mkdir -p /home/void/Desktop && \
    cp /home/void/.local/share/applications/void.desktop /home/void/Desktop/ && \
    chmod +x /home/void/Desktop/void.desktop

USER root

# Create a README for Docker-specific notes
RUN echo '#!/bin/bash\n\
cat << "EOF"\n\
========================================\n\
    Void Editor in Docker Container\n\
========================================\n\
\n\
IMPORTANT NOTES:\n\
----------------\n\
1. Due to Docker container limitations, Void runs with:\n\
   - --password-store=basic (API keys stored in plain text)\n\
   - --disable-gpu (GPU acceleration disabled)\n\
   \n\
2. This configuration is suitable for testing but NOT for production.\n\
   \n\
3. To start Void manually, use:\n\
   /usr/share/void/void --password-store=basic --disable-gpu\n\
   \n\
4. If you encounter issues with API keys:\n\
   - Clear the config: rm -rf ~/.config/Void\n\
   - Restart Void and re-enter your API keys\n\
   \n\
5. The Roo-Code extension is pre-installed.\n\
\n\
========================================\n\
EOF\n\
' > /home/void/README_DOCKER.txt && \
    chmod 644 /home/void/README_DOCKER.txt && \
    chown void:void /home/void/README_DOCKER.txt

# Create startup script
RUN echo '#!/bin/bash\n\
set -e\n\
\n\
# Set VNC password from environment variable (K8s provides this)\n\
if [ ! -z "$VNC_PASSWORD" ]; then\n\
    echo "Setting VNC password from environment variable..."\n\
    echo "$VNC_PASSWORD" | su - void -c "vncpasswd -f > /home/void/.vnc/passwd"\n\
    su - void -c "chmod 600 /home/void/.vnc/passwd"\n\
else\n\
    echo "WARNING: VNC_PASSWORD not set, using default password void"\n\
    echo "void" | su - void -c "vncpasswd -f > /home/void/.vnc/passwd"\n\
    su - void -c "chmod 600 /home/void/.vnc/passwd"\n\
fi\n\
\n\
# Start SSH daemon\n\
echo "Starting SSH daemon..."\n\
service ssh start\n\
\n\
# Start D-Bus\n\
if [ ! -d /var/run/dbus ]; then\n\
    mkdir -p /var/run/dbus\n\
fi\n\
dbus-daemon --system --fork || true\n\
\n\
# Set display\n\
export DISPLAY=:1\n\
export USER=void\n\
\n\
# Function to start VNC\n\
start_vnc() {\n\
    echo "Starting VNC server..."\n\
    \n\
    # Clean up any existing X11 locks, sockets and VNC processes\n\
    echo "Cleaning up old sessions..."\n\
    su - void -c "vncserver -kill :1 2>/dev/null || true"\n\
    sleep 1\n\
    rm -f /tmp/.X11-unix/X1 2>/dev/null || true\n\
    rm -f /tmp/.X1-lock 2>/dev/null || true\n\
    rm -f /home/void/.vnc/*.log 2>/dev/null || true\n\
    rm -f /home/void/.vnc/*.pid 2>/dev/null || true\n\
    pkill -9 Xtigervnc 2>/dev/null || true\n\
    pkill -9 Xvnc 2>/dev/null || true\n\
    # Clean up unix domain socket\n\
    rm -rf /tmp/.X11-unix 2>/dev/null || true\n\
    mkdir -p /tmp/.X11-unix\n\
    chmod 1777 /tmp/.X11-unix\n\
    sleep 2\n\
    \n\
    # Start VNC with retry logic\n\
    for i in 1 2 3; do\n\
        echo "VNC start attempt $i..."\n\
        if su - void -c "vncserver :1 -geometry 1920x1080 -depth 24 -localhost no 2>&1"; then\n\
            echo "VNC server started successfully"\n\
            break\n\
        else\n\
            echo "VNC start attempt $i failed, cleaning up and retrying..."\n\
            su - void -c "vncserver -kill :1 2>/dev/null || true"\n\
            sleep 1\n\
            rm -f /tmp/.X11-unix/X1 2>/dev/null || true\n\
            rm -f /tmp/.X1-lock 2>/dev/null || true\n\
            rm -f /home/void/.vnc/*.log 2>/dev/null || true\n\
            rm -f /home/void/.vnc/*.pid 2>/dev/null || true\n\
            pkill -9 Xtigervnc 2>/dev/null || true\n\
            pkill -9 Xvnc 2>/dev/null || true\n\
            rm -rf /tmp/.X11-unix 2>/dev/null || true\n\
            mkdir -p /tmp/.X11-unix\n\
            chmod 1777 /tmp/.X11-unix\n\
            sleep 2\n\
        fi\n\
    done\n\
    \n\
    # Check if VNC is running\n\
    sleep 2\n\
    if netstat -tuln | grep -q 5901; then\n\
        echo "VNC server is listening on port 5901"\n\
        return 0\n\
    else\n\
        echo "ERROR: VNC server failed to start"\n\
        return 1\n\
    fi\n\
}\n\
\n\
# Start VNC\n\
if start_vnc; then\n\
    # Start noVNC only if VNC is running\n\
    echo "Starting noVNC web interface..."\n\
    websockify --web=/usr/share/novnc/ 6080 localhost:5901 &\n\
    sleep 2\n\
    \n\
    echo ""\n\
    echo "===================================="\n\
    echo "VNC Server started on port 5901"\n\
    echo "noVNC web interface on port 6080"\n\
    echo ""\n\
    echo "Connect via:"\n\
    echo "  VNC Viewer: localhost:5901"\n\
    echo "  Web Browser: http://localhost:6080/vnc.html"\n\
    echo "  Password: $VNC_PASSWORD (or void if not set)"\n\
    echo "===================================="\n\
    echo ""\n\
    \n\
    # Start void if VOID_SK_TOKEN is provided\n\
    if [ ! -z "$VOID_SK_TOKEN" ]; then\n\
        echo "Starting Void with provided token..."\n\
        # Debug: Print token info\n\
        TOKEN_LENGTH=${#VOID_SK_TOKEN}\n\
        echo "Token length: $TOKEN_LENGTH"\n\
        if [ "$TOKEN_LENGTH" -gt 10 ]; then\n\
            echo "Token starts with: ${VOID_SK_TOKEN:0:10}..."\n\
        fi\n\
        \n\
        # Create a script to start void with proper environment\n\
        cat > /tmp/start_void.sh << EOFSCRIPT\n\
#!/bin/bash\n\
export DISPLAY=:1\n\
export VOID_SK_TOKEN="$VOID_SK_TOKEN"\n\
echo "Starting void with token: \${VOID_SK_TOKEN:0:10}..."\n\
/usr/share/void/void --skToken "\$VOID_SK_TOKEN" --no-sandbox --disable-gpu-sandbox > /tmp/void.log 2>&1\n\
EOFSCRIPT\n\
        chmod +x /tmp/start_void.sh\n\
        \n\
        # Start void as the void user\n\
        su - void -c "/tmp/start_void.sh &"\n\
        \n\
        # Wait and check if void started\n\
        sleep 3\n\
        if pgrep -f "/usr/share/void/void" > /dev/null; then\n\
            echo "Void process started successfully"\n\
        else\n\
            echo "WARNING: Void process may have failed to start"\n\
            echo "Check /tmp/void.log for details"\n\
            if [ -f /tmp/void.log ]; then\n\
                echo "First 10 lines of void.log:"\n\
                head -10 /tmp/void.log\n\
            fi\n\
        fi\n\
    else\n\
        echo "VOID_SK_TOKEN not provided, Void needs to be started manually"\n\
    fi\n\
else\n\
    echo "Failed to start VNC server after multiple attempts"\n\
    echo "You can manually start it by running:"\n\
    echo "  docker exec -it void-desktop-test su - void -c \"vncserver :1 -geometry 1920x1080 -depth 24 -localhost no\""\n\
fi\n\
\n\
# Keep container running regardless of VNC status\n\
tail -f /dev/null\n\
' > /start.sh && chmod +x /start.sh

# VNC xstartup configuration
USER void
RUN echo '#!/bin/bash\n\
unset SESSION_MANAGER\n\
unset DBUS_SESSION_BUS_ADDRESS\n\
\n\
# Start dbus\n\
eval $(dbus-launch --sh-syntax)\n\
\n\
# Start XFCE desktop (use exec to keep the script running)\n\
exec startxfce4\n\
' > /home/void/.vnc/xstartup && chmod +x /home/void/.vnc/xstartup

USER root

# Expose ports
EXPOSE 5901 6080 22

# Start services
CMD ["/start.sh"]