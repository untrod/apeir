# Homebrew formula for Nous Runtime
# Usage: brew install nous-runtime

class NousRuntime < Formula
  desc "Open modular intelligence runtime"
  homepage "https://github.com/nous-runtime/nous"
  version "1.1.0"
  license "Apache-2.0"

  depends_on "python@3.11"
  depends_on "tesseract" => :optional

  resource "typer" do
    url "https://files.pythonhosted.org/packages/.../typer-0.9.0.tar.gz"
    sha256 "..."
  end

  def install
    python3 = Formula["python@3.11"].opt_bin/"python3.11"
    system python3, "-m", "pip", "install", *std_pip_args, "."

    # Install CLI completion
    generate_completions_from_executable(bin/"nous", shells: [:bash, :zsh, :fish])
  end

  def post_install
    ohai "Nous Runtime installed!"
    ohai "Start: nous start"
    ohai "Shell: nous"
    ohai "Docs:  https://github.com/nous-runtime/nous"
  end

  test do
    system bin/"nous", "version"
  end
end
