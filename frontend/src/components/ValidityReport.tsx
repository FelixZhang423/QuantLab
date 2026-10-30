import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  ExclamationCircleOutlined,
  RobotOutlined,
} from "@ant-design/icons";
import { Card, Col, Flex, Progress, Row, Space, Tag, Typography } from "antd";
import type { ReactNode } from "react";
import {
  validityColor,
  validityTagColor,
  type ValidityGrade,
  type ValidityReport as ValidityReportData,
} from "../factorValidity";

const { Paragraph, Text } = Typography;

function gradeIcon(grade: ValidityGrade): ReactNode {
  switch (grade) {
    case "优秀":
    case "良好":
      return <CheckCircleOutlined />;
    case "合格":
      return <ExclamationCircleOutlined />;
    default:
      return <CloseCircleOutlined />;
  }
}

type Props = {
  report: ValidityReportData;
  title?: string;
  /** 嵌入抽屉/弹层时去掉外层 Card */
  bare?: boolean;
  /** 前端原型数据标记 */
  prototype?: boolean;
};

export function ValidityReport({ report, title = "大模型因子有效性评价", bare = false, prototype = false }: Props) {
  const content = (
    <Space direction="vertical" size={16} className="full-width">
      <div className="validity-summary">
        <Flex align="center" gap={20} wrap>
          <div className="validity-overall">
            <Progress
              type="circle"
              percent={report.overall}
              size={118}
              strokeColor={validityColor(report.grade)}
              trailColor="#edf0f4"
              format={(percent) => (
                <span className="validity-overall-number">
                  {percent}
                  <small>分</small>
                </span>
              )}
            />
            <div className="validity-overall-label">综合有效性</div>
          </div>
          <div className="validity-summary-body">
            <Space size={8} wrap>
              <Tag icon={gradeIcon(report.grade)} color={validityTagColor(report.grade)}>
                {report.grade}
              </Tag>
              <Text strong>{report.qualified ? "达到合格线" : "未达到合格线"}</Text>
              <Text type="secondary">合格线 {report.threshold} 分</Text>
              {prototype && <Tag color="purple">原型评价</Tag>}
            </Space>
            <Paragraph className="validity-conclusion">{report.conclusion}</Paragraph>
          </div>
        </Flex>
      </div>

      <Row gutter={[12, 12]}>
        {report.items.map((item) => (
          <Col xs={24} sm={12} xl={6} key={item.key}>
            <div className="validity-item">
              <Flex justify="space-between" align="center" className="validity-item-head" gap={8}>
                <Text strong>{item.label}</Text>
                <Tag icon={gradeIcon(item.grade)} color={validityTagColor(item.grade)}>
                  {item.grade}
                </Tag>
              </Flex>
              <Progress
                percent={item.score}
                showInfo={false}
                size="small"
                strokeColor={validityColor(item.grade)}
                trailColor="#edf0f4"
              />
              <Flex justify="space-between" className="validity-item-value" gap={8}>
                <Text type="secondary" ellipsis>
                  {item.value}
                </Text>
                <Text strong>{item.score}</Text>
              </Flex>
              <Paragraph type="secondary" className="validity-item-comment" ellipsis={{ rows: 3 }}>
                {item.comment}
              </Paragraph>
              {!item.available && <Text type="secondary" className="validity-item-na">指标缺失 · 中性分</Text>}
            </div>
          </Col>
        ))}
      </Row>

      <Text type="secondary" className="validity-note">
        8 项评价覆盖 IC、RankIC、ICIR、分组单调性、多空收益、换手成本、覆盖率与风险收益；
        {prototype ? "当前为前端原型规则估算，接入大模型后替换为真实评语。" : "缺失指标按中性分处理。"}
      </Text>
    </Space>
  );

  if (bare) return content;

  return (
    <Card
      className="validity-card"
      title={
        <Space>
          <RobotOutlined />
          {title}
          {prototype && <Tag color="purple">前端原型</Tag>}
        </Space>
      }
      extra={<Text type="secondary">8 项加权综合分</Text>}
    >
      {content}
    </Card>
  );
}
