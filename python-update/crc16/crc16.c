#include <stdio.h>
#include <stdlib.h>

#define DEBUG

unsigned short getCRC16(unsigned char *b, int len)
{
  unsigned int v5;
  unsigned int v6;
  unsigned int crc = 0xFEEA;
  for (int u = 0; u < len; u++)
    {
      v5 = b[u] ^ ((crc >> 8) | (crc << 8));
      v6 = (unsigned short) ((((((v5 << 24) >> 28) ^ v5) << 12) ^ ((v5 << 24) >> 28)) ^ v5);
      crc = ((32 * v6) & 0x1FFF) ^ v6;
    }
  return crc;
}

void readFile(char* filename, unsigned char** buffer, long* filesize){
  FILE *fp;
  long lSize;

  fp = fopen ( filename , "rb" );
  if( !fp ) perror(filename),exit(1);

  fseek( fp , 0L , SEEK_END);
  lSize = ftell( fp );
  *filesize = lSize;
  rewind( fp );

  /* allocate memory for entire content */
  *buffer = calloc( 1, lSize+1 );
  if( !*buffer ) fclose(fp),fputs("memory alloc fails",stderr),exit(1);

  /* copy the file into the buffer */
  if( 1!=fread( *buffer , lSize, 1 , fp) )
  fclose(fp),free(*buffer),fputs("entire read fails",stderr),exit(1);

  fclose(fp);
}

int main(int argc, char *argv[])
{
  if(argc != 2){
    printf("Incorect number of arguments!\n");
    printf("Usage: ./crc16 <file>\n");
    exit(1);
  }

  unsigned char* buffer;
  long filesize = 0;
  readFile(argv[1], &buffer, &filesize);
  printf("File is %lu long.\n", filesize);
  unsigned int crcCalc;
#ifdef DEBUG
  printf("First 10 bytes:\n");
  for(int i=0; i<10; i++){
    printf("0x%02x \n", buffer[i]);
  }
  printf("Last 10 bytes:\n");
  for(int i=filesize-1; i>(filesize-1-10); i--){
    printf("0x%02x \n", buffer[i]);
  }
  
  unsigned char dataCurrent[3] = { 0x01, 0x02, 0x03 };
  crcCalc = getCRC16(dataCurrent, 3);
  printf("Test CRC over 3 bytes. Result should be 0x661b: CRC is: %i  in hex 0x%04x\n", crcCalc, crcCalc); // this example gives out 26139 wich is 0x661B in hex

  unsigned char espruino_2v05_438_p8_dafit_block0[] = {0x00,0x00,0x01,0x20,0x39,0x33,0x02,0x00,0x61,0x33,0x02,0x00,0x63,0x33,0x02,0x00,0x65,0x33,0x02,0x00,0x67,0x33,0x02,0x00,0x69,0x33,0x02,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x6b,0x33,0x02,0x00,0x6d,0x33,0x02,0x00,0x00,0x00,0x00,0x00,0x6f,0x33,0x02,0x00,0x7d,0x9d,0x03,0x00,0x95,0x92,0x02,0x00,0x73,0x33,0x02,0x00,0x99,0x97,0x02,0x00,0xf5,0x92,0x02,0x00,0x49,0x93,0x02,0x00,0x73,0x33,0x02,0x00,0xb5,0x99,0x02,0x00,0x73,0x33,0x02,0x00,0x73,0x33,0x02,0x00,0xc1,0x9d,0x03,0x00,0x73,0x33,0x02,0x00,0x73,0x33,0x02,0x00,0x73,0x33,0x02,0x00,0xe9,0xa3,0x02,0x00,0x73,0x33,0x02,0x00,0x73,0x33,0x02,0x00,0xbd,0x9d,0x03,0x00,0xf1,0x6f,0x02,0x00,0x73,0x33,0x02,0x00,0x73,0x33,0x02,0x00,0xd5,0x70,0x02,0x00,0x99,0x4b,0x03,0x00,0x69,0x5a,0x02,0x00,0x73,0x33,0x02,0x00,0x73,0x33,0x02,0x00,0x73,0x33,0x02,0x00,0x73,0x33,0x02,0x00,0x73,0x33,0x02,0x00,0x73,0x33,0x02,0x00,0x73,0x33,0x02,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x73,0x33,0x02,0x00,0x73,0x33,0x02,0x00,0x73,0x33,0x02,0x00,0x73,0x33,0x02,0x00,0x73,0x33,0x02,0x00,0xb1,0xa4,0x02,0x00,0x73,0x33,0x02,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00};
  crcCalc = getCRC16(espruino_2v05_438_p8_dafit_block0, 256);
  printf("Test CRC over espruino_2v05_438_p8_dafit_block0: CRC is: %i  in hex 0x%04x\n", crcCalc, crcCalc);
#endif

  crcCalc = getCRC16(buffer, filesize);
  printf ("CRC is: %i  in hex 0x%04x\n", crcCalc, crcCalc); // this example gives out 26139 wich is 0x661B in hex
  return 0;
}