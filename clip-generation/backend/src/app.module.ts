import { Module } from '@nestjs/common';
import { JobsModule } from './api/jobs.module';
import { OrchestratorModule } from './orchestrator/orchestrator.module';

@Module({
  imports: [JobsModule, OrchestratorModule],
})
export class AppModule {}
