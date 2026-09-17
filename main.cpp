#include <opencv2/opencv.hpp>
#include <iostream>

int main(int argc, char** argv) {
    if (argc < 3) return 1;
    cv::Mat image = cv::imread(argv[1]);
    if (image.empty()) return 1;
    cv::Mat mask = cv::Mat::zeros(image.size(), CV_8UC1);
    cv::rectangle(mask, cv::Point(image.cols - 150, image.rows - 50), cv::Point(image.cols, image.rows), cv::Scalar(255), -1);
    cv::Mat result;
    cv::inpaint(image, mask, result, 3, cv::INPAINT_TELEA);
    cv::imwrite(argv[2], result);
    return 0;
}
