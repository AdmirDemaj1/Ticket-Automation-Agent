import { ApiProperty } from '@nestjs/swagger';
import { Transform } from 'class-transformer';
import { IsEmail, IsString, MaxLength, MinLength } from 'class-validator';

const normalizeEmail = ({ value }: { value: unknown }) =>
  typeof value === 'string' ? value.trim().toLowerCase() : value;

export class RegisterDto {
  @ApiProperty() @Transform(normalizeEmail) @IsEmail() @MaxLength(254) email: string;
  @ApiProperty() @IsString() @MinLength(1) @MaxLength(100) name: string;
  @ApiProperty({ minLength: 12 }) @IsString() @MinLength(12) @MaxLength(128) password: string;
}

export class LoginDto {
  @ApiProperty() @Transform(normalizeEmail) @IsEmail() @MaxLength(254) email: string;
  @ApiProperty() @IsString() @MinLength(1) @MaxLength(128) password: string;
}
