cat <<'EOF' > /home/ubuntu/app/main.cpp
#include <opencv2/opencv.hpp>
#include <iostream>

int main(int argc, char** argv) {
    if (argc < 3) return 1;
    
    cv::Mat image = cv::imread(argv[1]);
    if (image.empty()) return 1;

    cv::Mat gray, mask, thresh;
    cv::cvtColor(image, gray, cv::COLOR_BGR2GRAY);

    // Text aur bright watermark regions highlight karne ke liye adaptive thresholding
    cv::threshold(gray, thresh, 200, 255, cv::THRESH_BINARY);

    // Center region par focus override (EstateX text area)
    mask = cv::Mat::zeros(image.size(), CV_8UC1);
    
    // Watermark bounding area mask expansion
    int startX = image.cols * 0.35;
    int endX = image.cols * 0.65;
    int startY = image.rows * 0.35;
    int endY = image.rows * 0.65;
    
    cv::rectangle(mask, cv::Point(startX, startY), cv::Point(endX, endY), cv::Scalar(255), -1);

    // Apply Telea Inpainting algorithm
    cv::Mat result;
    cv::inpaint(image, mask, result, 7, cv::INPAINT_TELEA);

    cv::imwrite(argv[2], result);
    return 0;
}
EOF
