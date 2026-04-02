import {
  Controller,
  Post,
  Get,
  Param,
  Body,
  Headers,
  UploadedFiles,
  UseInterceptors,
  HttpCode,
  HttpStatus,
  NotFoundException,
  BadRequestException,
} from '@nestjs/common';
import { FileFieldsInterceptor } from '@nestjs/platform-express';
import { JobsService } from './jobs.service';
import { CreateJobDto, RetryJobDto } from './dto';

@Controller('jobs')
export class JobsController {
  constructor(private readonly jobsService: JobsService) {}

  @Post()
  @HttpCode(HttpStatus.CREATED)
  @UseInterceptors(
    FileFieldsInterceptor([
      { name: 'audio', maxCount: 1 },
      { name: 'photo', maxCount: 1 },
    ]),
  )
  async createJob(
    @Body() dto: CreateJobDto,
    @UploadedFiles() files: { audio?: Express.Multer.File[]; photo?: Express.Multer.File[] },
    @Headers('idempotency-key') idempotencyKey?: string,
  ) {
    if (!files?.audio?.[0]) throw new BadRequestException('audio file is required');
    if (!files?.photo?.[0]) throw new BadRequestException('photo file is required');

    return this.jobsService.createJob(
      dto,
      files.audio[0],
      files.photo[0],
      idempotencyKey || dto.idempotency_key,
    );
  }

  @Get(':jobId')
  async getJobStatus(@Param('jobId') jobId: string) {
    const job = await this.jobsService.getJobStatus(jobId);
    if (!job) throw new NotFoundException('Job not found');
    return job;
  }

  @Get(':jobId/result')
  async getJobResult(@Param('jobId') jobId: string) {
    const result = await this.jobsService.getJobResult(jobId);
    if (!result) throw new NotFoundException('Job not found');
    return result;
  }

  @Post(':jobId/retry')
  async retryJob(@Param('jobId') jobId: string, @Body() dto: RetryJobDto) {
    const job = await this.jobsService.retryJob(jobId, dto.from_step);
    if (!job) throw new NotFoundException('Job not found');
    return job;
  }

  @Post(':jobId/cancel')
  async cancelJob(@Param('jobId') jobId: string) {
    const job = await this.jobsService.cancelJob(jobId);
    if (!job) throw new NotFoundException('Job not found');
    return job;
  }
}
