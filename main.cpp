#include <iostream>
#include <stdlib.h>
#include <string>

using std::cout;
using std::to_string;
using std::string;

// Default configuration values. Each can be overridden via a command-line
// argument; when an argument is omitted the corresponding default is used.
#define DEFAULT_DOC_ID "62283426"
#define DEFAULT_PAGES_TOTAL 200
#define DEFAULT_DIMENSIONS "1215x1600"
#define DEFAULT_IMAGE_NAME "composicion-escrita.jpg"
#define DEFAULT_OUTPUT_NAME "composicion-escrita.pdf"

struct Config {
  string docId      = DEFAULT_DOC_ID;
  int pagesTotal    = DEFAULT_PAGES_TOTAL;
  string dimensions = DEFAULT_DIMENSIONS;
  string imageName  = DEFAULT_IMAGE_NAME;
  string outputName = DEFAULT_OUTPUT_NAME;
};

Config parseArgs(int argc, char *argv[]);
string concatenateURL(const Config &config, int page);
void downloadPage(const string &URL, int page);
void convertToPdf(const Config &config);
void deleteAllJPGs(const Config &config);
string getAllPagesString(const Config &config);

int main(int argc, char *argv[]) {

  Config config = parseArgs(argc, argv);

  for (int page = 1; page <= config.pagesTotal; page++) {
    string URL = concatenateURL(config, page);
    downloadPage(URL, page);
  }

  cout << "\nConverting...";
  convertToPdf(config);

  cout << "Deleting residual files...\n";
  deleteAllJPGs(config);

  return 0;
}

Config parseArgs(int argc, char *argv[]) {
  Config config;

  if (argc > 1) config.docId      = argv[1];
  if (argc > 2) config.pagesTotal = atoi(argv[2]);
  if (argc > 3) config.dimensions = argv[3];
  if (argc > 4) config.imageName  = argv[4];
  if (argc > 5) config.outputName = argv[5];

  return config;
}

string concatenateURL(const Config &config, int page) {

  string urlPath1 = "https://img.yumpu.com/" + config.docId + "/";
  string urlPath2 = "/" + config.dimensions + "/" + config.imageName;

  return urlPath1 + to_string(page) + urlPath2;

}

string getAllPagesString(const Config &config) {
  string allPagesSeparatedBySpaces = "";

  for (int page = 1; page <= config.pagesTotal; page++) {
    string filename = "page" + to_string(page) + ".jpg";

    allPagesSeparatedBySpaces += filename + " ";
  }

  return allPagesSeparatedBySpaces;
}

void downloadPage(const string &URL, int page) {

  string filename = "page" + to_string(page) + ".jpg";

  system("clear || cls");

  cout << "=== Downloading page " << page << " as " << filename << " ===" << std::endl;

  string concatenatedCommand = "curl " + URL + " --output " + filename;
  system(concatenatedCommand.c_str());

}

void convertToPdf(const Config &config) {

  string concatenatedCommand = "convert " + getAllPagesString(config) + " " + config.outputName;

  system(concatenatedCommand.c_str());

}

void deleteAllJPGs(const Config &config) {
  string concatenatedCommand = "rm " + getAllPagesString(config);

  system(concatenatedCommand.c_str());
}
